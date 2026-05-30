"""Authentication: salted scrypt password hashing, env-var admin override, login lockout.

Pragmatic production auth for the PHQ monitoring system. Uses Python's stdlib `hashlib.scrypt`
so we have NO new dependencies. Passwords stored in the `users` table are migrated transparently
on first run from plaintext (demo seed) to `scrypt$<N>$<r>$<p>$<salt_hex>$<hash_hex>`.

Environment overrides (optional, recommended for production):
  PHQ_ADMIN_PASSWORD   plaintext admin password — overrides any DB value on every login attempt
                       so an operator who has lost DB access can still get in.
  PHQ_AUTH_PEPPER      extra secret appended to every password before hashing. Without this
                       env var, the system uses a fixed default pepper (still salted per user,
                       but reviewers should set this in production).
"""
from __future__ import annotations
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional, Tuple

# scrypt parameters — chosen so a single verify runs in ~50–100 ms on a typical server.
# Higher than PBKDF2 defaults for the same wall-time, recommended by NIST/OWASP.
_SCRYPT_N = 2 ** 14    # CPU/memory cost
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

# Default pepper (fixed but not secret — env var overrides). The per-user random salt is what
# protects against rainbow tables; pepper adds a layer that requires DB+code compromise together.
_DEFAULT_PEPPER = b"phq-monitoring-2026"

# Login lockout policy — kept lightweight and in-process (no DB writes per failed attempt).
LOCKOUT_MAX_FAILS = 5
LOCKOUT_WINDOW_SECONDS = 300   # 5-minute rolling window
LOCKOUT_DURATION_SECONDS = 300


def _pepper() -> bytes:
    return os.environ.get("PHQ_AUTH_PEPPER", "").encode("utf-8") or _DEFAULT_PEPPER


def hash_password(plaintext: str) -> str:
    """Return a self-describing hash string: scrypt$<N>$<r>$<p>$<salt_hex>$<hash_hex>."""
    if plaintext is None:
        plaintext = ""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        (plaintext + _pepper().decode("latin1")).encode("utf-8"),
        salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def is_hashed(stored: str) -> bool:
    return isinstance(stored, str) and stored.startswith("scrypt$")


def verify_password(plaintext: str, stored: Optional[str]) -> bool:
    """Constant-time verify against a `scrypt$...` string. Returns False on any malformed input."""
    if not stored:
        return False
    if not is_hashed(stored):
        # legacy plaintext rows — equality compare (will be re-hashed on next successful login)
        return hmac.compare_digest(str(plaintext), str(stored))
    try:
        _, n, r, p, salt_hex, hash_hex = stored.split("$")
        n, r, p = int(n), int(r), int(p)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt(
            (plaintext + _pepper().decode("latin1")).encode("utf-8"),
            salt=salt, n=n, r=r, p=p, dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def env_admin_override(username: str, plaintext: str) -> bool:
    """If PHQ_ADMIN_PASSWORD is set, accept it for the 'admin' username."""
    env_pw = os.environ.get("PHQ_ADMIN_PASSWORD", "")
    if not env_pw or username.strip().lower() != "admin":
        return False
    return hmac.compare_digest(plaintext, env_pw)


# ---------------- lockout ---------------------------------------------------
def _bucket(state: dict, username: str) -> dict:
    return state.setdefault("_login_attempts", {}).setdefault(username, {"fails": [], "locked_until": 0.0})


def is_locked(state: dict, username: str) -> Tuple[bool, int]:
    """Return (locked?, seconds_remaining)."""
    b = _bucket(state, username)
    now = time.time()
    if b["locked_until"] > now:
        return True, int(b["locked_until"] - now)
    return False, 0


def record_failure(state: dict, username: str) -> Tuple[bool, int]:
    """Record a failed attempt; lock the user if they've exceeded the policy. Returns (locked?, fails_in_window)."""
    b = _bucket(state, username)
    now = time.time()
    b["fails"] = [t for t in b["fails"] if now - t <= LOCKOUT_WINDOW_SECONDS]
    b["fails"].append(now)
    if len(b["fails"]) >= LOCKOUT_MAX_FAILS:
        b["locked_until"] = now + LOCKOUT_DURATION_SECONDS
        b["fails"] = []
        return True, LOCKOUT_MAX_FAILS
    return False, len(b["fails"])


def record_success(state: dict, username: str) -> None:
    state.setdefault("_login_attempts", {}).pop(username, None)


# ---------------- DB integration -------------------------------------------
def ensure_hashed_users(conn) -> int:
    """Re-hash any plaintext rows in `users`. Returns the number of rows migrated.

    Safe to call on every app start: rows already in `scrypt$...` form are left alone.
    """
    cur = conn.cursor()
    rows = cur.execute("SELECT user_id, password FROM users").fetchall()
    n = 0
    for r in rows:
        uid = r[0] if not isinstance(r, dict) else r["user_id"]
        pw = r[1] if not isinstance(r, dict) else r["password"]
        if pw and not is_hashed(pw):
            cur.execute("UPDATE users SET password=? WHERE user_id=?", (hash_password(pw), uid))
            n += 1
    if n:
        conn.commit()
    return n


def authenticate(conn, username: str, password: str) -> Optional[dict]:
    """Verify credentials against the users table. Returns the user record on success, else None.

    Also accepts the env-var admin override for the 'admin' username.
    Successful logins with a legacy plaintext password trigger an automatic re-hash.
    """
    if not username or password is None:
        return None
    cur = conn.cursor()
    row = cur.execute(
        "SELECT user_id, name, email, password, role, status FROM users WHERE LOWER(email)=? OR LOWER(name)=?",
        (f"{username.strip().lower()}@phq.demo", username.strip().lower()),
    ).fetchone()
    if row is None:
        # also accept by exact name (the seed uses "System Admin" etc.) — fall back to username==role lookup
        row = cur.execute(
            "SELECT user_id, name, email, password, role, status FROM users WHERE role=?",
            (username.strip().lower(),),
        ).fetchone()
    if row is None and not env_admin_override(username, password):
        return None
    if env_admin_override(username, password):
        return {"username": "admin", "name": "System Admin", "role": "admin", "source": "env-override"}
    if row["status"] and row["status"] != "active":
        return None
    if verify_password(password, row["password"]):
        # legacy plaintext → upgrade silently
        if not is_hashed(row["password"]):
            cur.execute("UPDATE users SET password=? WHERE user_id=?",
                        (hash_password(password), row["user_id"]))
            conn.commit()
        return {"username": username.strip(), "name": row["name"], "role": row["role"], "source": "db"}
    return None

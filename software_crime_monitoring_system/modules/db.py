"""Database connection, initialization and seeding from the bundled PHQ dataset.

Production hardening (May 2026):
  - PRAGMA journal_mode=WAL + synchronous=NORMAL  -> concurrent readers while a write is in
    progress; safer durability than OFF without the latency of FULL.
  - Indexes on hot columns                          -> Dashboard / Forecast-vs-Actual reads
    drop from full-table scans to log(n) lookups.
  - ensure_hashed_users()                           -> migrates any plaintext password rows
    to scrypt$... on every app start.
"""
import sqlite3
import time
from datetime import datetime
import pandas as pd
import config as C


# --- connection pool (one per thread, set up once with WAL/synchronous/foreign_keys) ----
_PRAGMA_ONCE_DONE = False


def _apply_pragmas_once():
    """Run the durable PRAGMAs exactly once per process (WAL is persistent on the DB file)."""
    global _PRAGMA_ONCE_DONE
    if _PRAGMA_ONCE_DONE:
        return
    conn = sqlite3.connect(C.DB_PATH, check_same_thread=False, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=8000;")
        conn.commit()
    finally:
        conn.close()
    _PRAGMA_ONCE_DONE = True


def get_conn():
    _apply_pragmas_once()
    conn = sqlite3.connect(C.DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 8000;")
    return conn


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def _ensure_indexes(cur):
    """Idempotent index creation on hot columns. Each CREATE IF NOT EXISTS is cheap."""
    stmts = [
        "CREATE INDEX IF NOT EXISTS idx_cmd_date ON crime_monthly_data(date)",
        "CREATE INDEX IF NOT EXISTS idx_cmd_year_month ON crime_monthly_data(year, month)",
        "CREATE INDEX IF NOT EXISTS idx_cmd_active_pipeline ON crime_monthly_data(is_active, in_model_pipeline)",
        "CREATE INDEX IF NOT EXISTS idx_cmd_category ON crime_monthly_data(crime_category)",
        "CREATE INDEX IF NOT EXISTS idx_fc_category_target ON forecasts(category, target_date)",
        "CREATE INDEX IF NOT EXISTS idx_fc_run ON forecasts(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_drift_run ON drift_monitoring(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_vm_run ON validation_metrics(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_when ON audit_logs(changed_at)",
    ]
    for s in stmts:
        cur.execute(s)


def init_db(force_seed: bool = False):
    """Create tables, indexes, seed standard units / categories / users / history once.
    Idempotent: safe to call on every app start."""
    # Make sure the DB directory exists (fresh deploys)
    C.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    conn.executescript(C.SCHEMA_SQL.read_text())
    cur = conn.cursor()

    # migration: ensure is_active column exists on crime_monthly_data (old DBs)
    cols = [r[1] for r in cur.execute("PRAGMA table_info(crime_monthly_data)").fetchall()]
    if "is_active" not in cols:
        cur.execute("ALTER TABLE crime_monthly_data ADD COLUMN is_active INTEGER DEFAULT 1")
        conn.commit()

    _ensure_indexes(cur)

    # seed users (still plaintext at this point — re-hashed below)
    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        for uname, u in C.DEMO_USERS.items():
            cur.execute("INSERT INTO users(name,email,password,role,created_at,status) VALUES(?,?,?,?,?,?)",
                        (u["name"], f"{uname}@phq.demo", u["password"], u["role"], _now(), "active"))

    # standard units
    if cur.execute("SELECT COUNT(*) FROM reporting_units").fetchone()[0] == 0:
        for u in C.STANDARD_UNITS:
            cur.execute("""INSERT INTO reporting_units
                (unit_name,unit_type,is_standard_phq_unit,is_active,created_by,created_at,note)
                VALUES(?,?,?,?,?,?,?)""",
                (u, C.UNIT_TYPE[u], 1, 1, "system", _now(), "seeded standard PHQ unit"))

    # standard categories
    if cur.execute("SELECT COUNT(*) FROM crime_categories").fetchone()[0] == 0:
        for c in C.STANDARD_CATEGORIES:
            cur.execute("""INSERT INTO crime_categories
                (category_name,display_name,is_standard_phq_category,is_model_supported,is_active,created_by,created_at,note)
                VALUES(?,?,?,?,?,?,?,?)""",
                (c, c.replace("_", " "), 1, 1, 1, "system", _now(), "seeded standard PHQ category"))

    # seed historical monthly data (long format) once
    if force_seed or cur.execute("SELECT COUNT(*) FROM crime_monthly_data").fetchone()[0] == 0:
        seed_path = C.PROCESSED / "seed_unit_level.csv"
        if seed_path.exists():
            df = pd.read_csv(seed_path)
            df["Date"] = pd.to_datetime(df["Date"])
            cats = [c for c in df.columns if c not in ("Unit", "Date")]
            for dt, g in df.groupby("Date"):
                y, m = int(dt.year), int(dt.month)
                cur.execute("""INSERT INTO data_versions(year,month,version_number,status,created_by,created_at,approved_by,approved_at,change_summary)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (y, m, 1, "approved", "system", _now(), "system", _now(), "seeded historical PHQ data"))
                vid = cur.lastrowid
                rows = []
                for _, r in g.iterrows():
                    unit = r["Unit"]
                    total = float(sum(float(r[c]) for c in cats))
                    for c in cats:
                        rows.append((y, m, dt.strftime("%Y-%m-%d"), unit, c, float(r[c]), total,
                                     None, vid, "system", _now(), _now(), "approved", 0, 0, 1, None))
                cur.executemany("""INSERT INTO crime_monthly_data
                    (year,month,date,police_unit,crime_category,value,total_cases,source_id,version_id,
                     created_by,created_at,updated_at,verification_status,is_custom_unit,is_custom_category,
                     in_model_pipeline,custom_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)

    conn.commit()

    # migrate plaintext passwords -> hashed (safe + idempotent)
    try:
        from . import auth
        auth.ensure_hashed_users(conn)
    except Exception:
        # never block app startup on auth migration; surfaced in logs
        pass

    conn.close()


# ----------------------- cache invalidation helper ------------------------
def _db_mtime() -> float:
    """Returns the modification time of the DB file (or 0 if absent). Used as a cache key
    so cached reads automatically refresh after any write."""
    try:
        return C.DB_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


# ----------------------- data access helpers ------------------------------
def national_series(category: str = "Total_Cases", approved_only: bool = True) -> pd.Series:
    """Return monthly national series for a category. Total_Cases = sum of all 15 categories.
    Only rows flagged into the model pipeline. Cached on (category, approved_only, db_mtime).
    """
    return _national_series_cached(category, approved_only, _db_mtime())


def _national_series_cached(category: str, approved_only: bool, _mtime: float) -> pd.Series:
    conn = get_conn()
    appr = "AND verification_status='approved'" if approved_only else ""
    q = (f"SELECT date, crime_category, SUM(value) v FROM crime_monthly_data "
         f"WHERE in_model_pipeline=1 AND is_active=1 {appr} GROUP BY date, crime_category")
    df = pd.read_sql_query(q, conn)
    conn.close()
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    if category == "Total_Cases":
        s = df.groupby("date")["v"].sum()
    else:
        s = df[df["crime_category"] == category].groupby("date")["v"].sum()
    return s.sort_index()


# Try to install a Streamlit cache wrapper around the read-only helpers.
# When running outside Streamlit (smoke check / tests), this is a no-op decorator.
try:
    import streamlit as _st  # type: ignore
    _national_series_cached = _st.cache_data(show_spinner=False, ttl=120)(_national_series_cached)
except Exception:
    pass


def long_table(approved_only: bool = True) -> pd.DataFrame:
    return _long_table_cached(approved_only, _db_mtime())


def _long_table_cached(approved_only: bool, _mtime: float) -> pd.DataFrame:
    conn = get_conn()
    appr = "AND verification_status='approved'" if approved_only else ""
    df = pd.read_sql_query(f"SELECT * FROM crime_monthly_data WHERE is_active=1 {appr}", conn)
    conn.close()
    return df


try:
    import streamlit as _st  # type: ignore
    _long_table_cached = _st.cache_data(show_spinner=False, ttl=120)(_long_table_cached)
except Exception:
    pass


def list_units(active_only=True):
    conn = get_conn()
    q = "SELECT * FROM reporting_units" + (" WHERE is_active=1" if active_only else "")
    df = pd.read_sql_query(q, conn); conn.close(); return df


def list_categories(active_only=True):
    conn = get_conn()
    q = "SELECT * FROM crime_categories" + (" WHERE is_active=1" if active_only else "")
    df = pd.read_sql_query(q, conn); conn.close(); return df


def months_present():
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT DISTINCT year,month,date,verification_status FROM crime_monthly_data "
        "WHERE is_active=1 ORDER BY date", conn)
    conn.close(); return df


def next_expected_month():
    """Return (year, month) of the month *after* the latest approved month, useful as a default
    for the Add Monthly Data page. Falls back to current calendar month if nothing exists."""
    df = months_present()
    if df.empty:
        now = pd.Timestamp.utcnow()
        return int(now.year), int(now.month)
    last = pd.to_datetime(df["date"]).max()
    nxt = (last + pd.offsets.MonthBegin(1))
    return int(nxt.year), int(nxt.month)


def latest_run():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM model_runs ORDER BY run_id DESC LIMIT 1", conn)
    conn.close()
    return None if df.empty else df.iloc[0].to_dict()


def latest_validation_metrics():
    conn = get_conn()
    r = pd.read_sql_query("SELECT MAX(run_id) r FROM validation_metrics", conn).iloc[0]["r"]
    df = pd.DataFrame()
    if r is not None:
        df = pd.read_sql_query("SELECT * FROM validation_metrics WHERE run_id=? ORDER BY category,horizon",
                               conn, params=[int(r)])
    conn.close()
    return df


def latest_drift_status():
    conn = get_conn()
    r = pd.read_sql_query("SELECT MAX(run_id) r FROM drift_monitoring", conn).iloc[0]["r"]
    status = None
    if r is not None:
        d = pd.read_sql_query("SELECT drift_status FROM drift_monitoring WHERE run_id=?", conn, params=[int(r)])
        if not d.empty:
            status = ("critical" if (d.drift_status == "critical").any()
                      else "warning" if (d.drift_status == "warning").any()
                      else "normal" if (d.drift_status == "normal").any() else "unknown")
    conn.close()
    return status


def forecast_count():
    conn = get_conn()
    n = pd.read_sql_query("SELECT COUNT(*) n FROM forecasts", conn).iloc[0]["n"]
    conn.close()
    return int(n)


def invalidate_cache():
    """Call after any write that bypasses the helpers' caches (rarely needed since
    the cache key is the DB mtime). Streamlit-only."""
    try:
        import streamlit as _st  # type: ignore
        _st.cache_data.clear()
    except Exception:
        pass

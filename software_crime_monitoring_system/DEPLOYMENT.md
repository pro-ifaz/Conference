# Deployment Guide

The app is a Streamlit + SQLite system. Below are four ways to run it, from easiest (live demo)
to a hardened production deployment. As of the **May 2026 production pass**, the framework ships
in production mode by default: hashed passwords (scrypt + per-user salt + optional pepper),
WAL-mode SQLite, full model sweep (no demo shortcuts), and cross-platform timeouts.

---

## Option 1 — Local (single-machine / defense)
```bash
# 1. Python 3.10–3.12 recommended
python --version

# 2. Install
cd software_crime_monitoring_system
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. (Production) Set the env vars BEFORE the first run
export PHQ_ADMIN_PASSWORD="<a strong password you remember>"   # overrides the admin DB row
export PHQ_AUTH_PEPPER="<a long random string, keep secret>"   # added to every hash
# (optional) export PHQ_SHOW_LOGIN_HINT=0                       # hide the seed-creds caption (default)
# (optional) export PHQ_FAST_DEMO_MODE=0                        # full models/horizons (default)
# (optional) export PHQ_MODEL_TIMEOUT=20                        # seconds per risky fit

# 4. Run
streamlit run app.py
# open http://localhost:8501
```
The database seeds itself on first launch. To **reset** the demo, delete
`database/crime_monitoring.db` and rerun.

**First-run note:** the four seed users (admin / operator / reviewer / viewer) are inserted with
their default plaintext passwords *only on the very first init*. They are immediately re-hashed
with scrypt — the DB never contains plaintext on rest after the first boot. Re-running with
`PHQ_ADMIN_PASSWORD` set lets you sign in even if you've forgotten the seed password.

---

## Option 2 — Streamlit Community Cloud
1. Push the `software_crime_monitoring_system/` folder to a public GitHub repo.
2. Go to https://share.streamlit.io → **New app** → pick the repo → set **Main file path** = `app.py`.
3. In the app's **Secrets** tab, add at minimum:
   ```toml
   PHQ_ADMIN_PASSWORD = "your-strong-admin-password"
   PHQ_AUTH_PEPPER    = "your-long-random-secret"
   ```
4. Deploy. The app seeds its SQLite DB on first load.

Note that Community Cloud storage is **ephemeral** — the SQLite DB resets on each cold start.
That's fine for a demo (it re-seeds the 76-month history automatically), but for persistent
operational data use Option 3 (Docker with a mounted volume).

---

## Option 3 — Docker (portable, persistent)
```dockerfile
# Dockerfile (place inside software_crime_monitoring_system/)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit","run","app.py","--server.port=8501","--server.address=0.0.0.0"]
```
```bash
docker build -t phq-monitoring .
docker run -d --name phq \
  -p 8501:8501 \
  -e PHQ_ADMIN_PASSWORD='strong-admin-pw' \
  -e PHQ_AUTH_PEPPER='long-random-secret' \
  -v $(pwd)/database:/app/database \
  -v $(pwd)/data/uploaded_sources:/app/data/uploaded_sources \
  phq-monitoring
```
The mounted volumes persist the SQLite DB and uploaded PHQ source PDFs across restarts.

---

## Option 4 — Hardening for a multi-user deployment
- **HTTPS** in front (nginx or Caddy reverse-proxying to Streamlit).
- **Backups:** nightly `sqlite3 database/crime_monitoring.db ".backup db.bak"` to off-host storage.
- **Rotate `PHQ_AUTH_PEPPER`** every 6–12 months. After rotation, the next successful login per user
  silently re-hashes the password with the new pepper (legacy hashes keep working until that login).
- **Forward `/data/uploaded_sources` to object storage** (S3/MinIO) instead of the local volume.
- **Switch the underlying DB to Postgres** once concurrency exceeds ~5 simultaneous writers
  (SQLite + WAL handles read concurrency fine but only one writer at a time).

---

## Operational loop (what the monthly cycle looks like)
1. PHQ releases a new monthly statement (PDF / web page).
2. Operator opens **Add Monthly Data**; the year/month fields auto-advance to the next expected
   month. Operator pastes the unit-level numbers in the editor or uploads a CSV/XLSX.
3. CSV upload is tolerant: UTF-8 / UTF-8-BOM / Latin-1, case-insensitive `.csv` / `.xlsx`,
   common header typos auto-mapped to PHQ standards (e.g. "Police Assault" → `Police_Assault`).
4. Operator runs **Validate** → fixes any critical errors → **Submit for approval**.
5. Reviewer/admin opens the same page, scrolls to the approval block, clicks
   **Approve and run recalibration**. The app:
   - approves the submitted version and deactivates any older versions for that month;
   - clears the in-memory forecast cache;
   - runs the full rolling-origin sweep (~60–120 s);
   - stores fresh validation metrics, drift status, stability labels, next forecasts, and
     leakage-free backtest comparisons.
6. Operator/reviewer opens **Forecast vs Actual**, **Drift Monitoring**, **Model Metrics** —
   all read from the persisted run, no recomputation needed.

---

## Performance characteristics (May 2026 production build)
| Operation                              | Wall time on seed dataset |
|----------------------------------------|---------------------------|
| First-boot init + seed                 | ~3 s                      |
| Full-mode recalibration (8 cats × 4 h) | ~60–120 s                 |
| Dashboard page load (cached read)      | < 200 ms                  |
| Rolling-origin per category (cached)   | < 1 s (5–15 s first time) |
| Login (single scrypt verify)           | ~50–100 ms                |

---

## Troubleshooting
- **Forgot admin password:** restart with `PHQ_ADMIN_PASSWORD=<new>` set in the env; that
  password works for `admin` until you remove the env var. (The DB row is untouched, so the
  old hashed password also still works.)
- **Locked account:** wait 5 minutes (configurable `LOCKOUT_DURATION_SECONDS` in `modules/auth.py`)
  or restart the Streamlit process (lockout state is in-memory only).
- **Blank/old data:** delete `database/crime_monitoring.db` (and `.db-wal`, `.db-shm`) to re-seed.
- **Slow recalibration:** expected in production mode (full model sweep). Run it once after each
  monthly approval; everything downstream reads from the persisted run.
- **LightGBM install issues on cloud:** safe to drop from `requirements.txt`; the framework logs a
  fallback to Seasonal Naive and keeps working.
- **CSV upload rejected:** check **Validation Report** — missing units, missing categories, or
  negative values are blocking failures. Custom rows/columns are accepted but excluded from the
  model pipeline until mapped to a standard PHQ name.

---

## Smoke test
A self-contained smoke check covers the seed, duplicate-month safety, forecasting, end-to-end
recalibration, DB-backed reads, and auth (hash-on-init + login + lockout):
```bash
python tests/smoke_check.py
# expect: SMOKE CHECK: 18/18 passed
```
It uses a temporary DB so it never touches your real `database/crime_monitoring.db`.

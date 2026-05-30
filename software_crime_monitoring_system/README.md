# PHQ Reported-Crime Monitoring System (Streamlit MVP)

An **official Police Headquarters (PHQ) reported-crime forecasting and monthly monitoring framework for
Bangladesh**. It is **not** a generic "AI crime prediction" tool: it forecasts officially **reported**
monthly crime counts, never claims perfect prediction, and never presents future scenario forecasts as
verified results.

It implements the monthly operational loop end to end:

> **PHQ monthly data release → data ingestion → cleaning & integrity audit → PHQ source provenance log
> → forecasting (FAST_SAFE) → actual-vs-forecast comparison → error dashboard & drift monitor →
> model recalibration → next forecast generation.**

## Scope notes (XAI and Federated Learning)
- **Explainable AI (XAI)** is included as a **supplementary interpretability** layer (feature
  influence, category-level error contribution, residual diagnostics). It is diagnostic only and does
  **not** change the forecasting model, the validation process, or any reported accuracy.
- **Federated Learning (FL) is not implemented** in the notebook or in this software. There is no FL
  page, module, dashboard, or training code.
- FL is discussed **only as a future secure-deployment direction** in the IEEE paper's Future Work
  section, for a possible deployment where sensitive raw records remain distributed across local
  police systems.
- The **current accuracy claims are not FL-based**; they come from the centralized, source-verified,
  leakage-free rolling-origin validation on aggregated public PHQ data.

## Features
- **Manual spreadsheet-like entry** (`st.data_editor`) preloaded with the 17 standard PHQ units (rows)
  and 15 categories (columns); numeric-only cells; **auto Total_Cases**; add custom rows/columns with a
  **required reason** (custom/unmapped fields are excluded from the forecasting pipeline unless mapped).
- **CSV/XLSX import** with preview + blank template download + export.
- **Source provenance** with **SHA-256 checksum** of the official PHQ PDF/URL.
- **Validation**: month duplication, 17 units present, 15 categories present, Total_Cases = sum,
  missing/negative checks, national = unit aggregation, extreme-change warning, custom-field control.
- **Forecast vs actual**, **error metrics** (MAPE, sMAPE, MAE, RMSE, true_MASE, WAPE),
  **drift monitor** (normal/warning/critical), **rolling-origin** validation (leakage-free; 1/3/6/12),
  **category stability** (stable vs hard/noisy), **recalibration**, **scenario projection** (clearly
  labelled), **audit log**, and **exports** (CSV/XLSX/PDF).
- **Models**: Naive, Seasonal Naive, ETS, Theta, ARIMA, SARIMA, LightGBM, FAST_SAFE Ensemble.
  **No Transformer** in the MVP (only a future-research note) — 76 monthly points is too short for it.

## Run locally
```bash
cd software_crime_monitoring_system
python -m venv .venv && source .venv/bin/activate        # optional
pip install -r requirements.txt

# (recommended for any non-demo deployment)
export PHQ_ADMIN_PASSWORD="<a strong password>"
export PHQ_AUTH_PEPPER="<a long random secret>"

streamlit run app.py
```
Open the printed URL (default http://localhost:8501). The SQLite DB and history are **seeded
automatically on first run** from the bundled dataset (`data/processed/seed_unit_level.csv`,
Jan 2020–Apr 2026, 76 months, 17 units). On that first init, the seed user passwords (see below)
are inserted in plaintext and **immediately re-hashed with scrypt** — the DB never holds plaintext
on rest after the first boot.

**Seed accounts** (re-hashed on init; change in production):
`admin/admin123`, `operator/operator123`, `reviewer/reviewer123`, `viewer/viewer123`.
Setting `PHQ_ADMIN_PASSWORD` in the environment also lets you log in as `admin` with that env
value regardless of the DB row — useful for recovery and first-time deploys.

## Typical operational flow
1. **Add Monthly Data** → year/month auto-advance to the next expected month → edit the table or
   upload CSV/XLSX (UTF-8 / UTF-8-BOM / Latin-1, case-insensitive `.csv`/`.xlsx`, common header
   typos auto-mapped to PHQ standard names) → attach PHQ PDF/URL → **Validate** →
   **Submit for approval** → (admin/reviewer) **Approve and recalibrate**.
2. **Validation Report**, **Source Provenance**, **Forecast vs Actual**, **Model Metrics**,
   **Drift Monitoring**, **Rolling-Origin**, **Category Stability**, **Scenario Projection**,
   **Audit Log**, **Export Reports**.

## Honesty boundaries (built in)
- `practical_accuracy = 100 − MAPE` is shown as a readability convention; MAPE/true_MASE are primary.
- Archived thesis verification (**92.5%** Total_Cases, Jun 2025–Apr 2026) is shown as **archived** and is
  **never mixed** with the live regenerated rolling-origin numbers.
- Scenario projections carry an explicit "not verified accuracy" warning and are capped at
  `MAX_SCENARIO_HORIZON_MONTHS` (36 months past the latest observation) to prevent runaway inputs.
- Custom district/area rows never silently enter the validated 17-unit pipeline.

See `DEPLOYMENT.md` (hosting, env vars, perf table) and `SRS.md` (requirements + defense explanation).


## Production hardening (May 2026 pass)
This build ships in production mode by default. Changes vs. the earlier demo build:

| Area | Change |
|---|---|
| Auth | scrypt-hashed passwords with per-user salt + optional pepper; legacy plaintext rows auto-migrated on first init; `PHQ_ADMIN_PASSWORD` env-var override for recovery; constant-time verify (`hmac.compare_digest`). |
| Login | 5-fails-in-5-minutes → 5-minute lockout; 0.5 s delay on failure to slow scripted brute force. Logout clears **all** session state, not just the user record. |
| Forecasting | SIGALRM-based timeout replaced by `concurrent.futures` so timeouts also work on Streamlit worker threads and on Windows. Per-process forecast cache is now a bounded LRU. |
| Database | `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` + busy-timeout for safe concurrent reads. Indexes on `crime_monthly_data(date)`, `(year,month)`, `(is_active,in_model_pipeline)`, `crime_category`; on `forecasts(category,target_date)`, `(run_id)`; on `drift_monitoring(run_id)`, `validation_metrics(run_id)`, `audit_logs(changed_at)`. Read helpers wrapped in `@st.cache_data` keyed by DB mtime so writes auto-invalidate. |
| CSV upload | Case-insensitive extension; UTF-8 / UTF-8-BOM / Latin-1 fallback; column-name normalization with fuzzy aliases ("Police Assault" → `Police_Assault`, "WCR" → `Woman_Child_Repression`, etc.). |
| Add-Monthly-Data UX | Year/month default auto-advance to the next expected month; editor and validation state cleared after a successful approval so the previous draft can't be re-submitted; cache invalidated on save/approve. |
| Rolling-Origin page | The expensive 8-model × 4-horizon × 5-fold sweep is now cached per category and gated behind a **Recompute now** button (used to run on every page load). |
| Scenario Projection | Date input bounded by `MAX_SCENARIO_HORIZON_MONTHS`. |
| Drift monitoring | Removed unreachable code that followed an early `return`; restored the `category_drift()` helper that had silently lost its `def` line. |
| Tests | Smoke check extended from 14 to 18 checks (added `G.*` covering hash-at-init, login, wrong-pw, lockout). |

### Run smoke checks
```bash
python tests/smoke_check.py
# expect: SMOKE CHECK: 18/18 passed
```
Uses an isolated temp DB so it never touches your real `database/crime_monitoring.db`.

### Switch back to fast demo mode (e.g. for a 2-minute thesis demo)
```bash
export PHQ_FAST_DEMO_MODE=1    # then start streamlit as usual
```
This restricts the recalibration sweep to the shortlist of models/horizons/categories in
`config.py` and shortens wall time to ~1–2 minutes. All persistence behaviour is unchanged.

### Add a new PHQ month
Add Monthly Data → year/month auto-fills to the next expected month → edit table or upload
CSV/XLSX → attach PHQ PDF/URL → Validate → Submit → (admin/reviewer) Approve & recalibrate.
Re-approving a month replaces it (active-version logic) and never doubles Total_Cases.

**Future forecasts are scenario projections only — not verified accuracy.**

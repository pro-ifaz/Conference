# Software Requirement Specification (concise) + Defense Explanation

## 1. Purpose
A monthly operational monitoring system around the validated PHQ reported-crime forecasting framework. It
lets an admin/researcher enter or import each newly released official PHQ month, verify its source,
validate integrity, compare the previous forecast against the new actual, refresh metrics and rolling-
origin validation, monitor drift, recalibrate, and generate the next forecast — all audit-logged.

## 2. Scope and identity
- Official **reported-crime** forecasting and **monthly monitoring framework** for Bangladesh.
- Forecasts **reported** counts only (not hidden/unreported crime); no causal or "perfect prediction" claim.
- Future projections are **scenario only**.

## 3. Users / roles
- **admin** (all), **operator** (enter/import/validate), **reviewer** (validate/approve), **viewer** (read).

## 4. Functional requirements (implemented in MVP)
1. Manual spreadsheet entry preloaded with 17 PHQ units + 15 categories; numeric-only; auto Total_Cases.
2. CSV/XLSX import with preview, template download, export.
3. Custom row/column addition with required reason; custom/unmapped fields excluded from the pipeline.
4. Mapping option for custom unit → standard PHQ unit.
5. Source provenance: PHQ URL, PDF, SHA-256, uploader, timestamp, verification status, reviewer note.
6. Validation: month duplication, 17 units, 15 categories, Total_Cases = sum, missing/negative,
   national = unit aggregation, extreme-change warning, custom-field control.
7. Versioning + approval workflow (draft → submitted → approved).
8. Forecast vs actual comparison and error metrics: MAPE, sMAPE, MAE, RMSE, true_MASE, WAPE.
9. Rolling-origin validation (no random split, no leakage; horizons 1/3/6/12; model/horizon/category).
10. Drift monitoring: normal/warning/critical + recommendation; connected to the feedback loop.
11. Category stability (stable vs hard/noisy; stable-watch re-label on rising error).
12. Recalibration: reload data → revalidate → drift → best-model-per-cell → next forecast → store run.
13. Scenario projection clearly labelled "not verified accuracy".
14. Audit log of all add/edit/approve actions, including custom-field changes.
15. Exports: CSV, XLSX, PDF.

## 5. Non-functional
- Reproducible (seed 42), relative paths, runs in Colab/local/Streamlit Cloud/Docker.
- No silent model failures: ETS/Theta/ARIMA/SARIMA/LightGBM fall back to Seasonal Naive **with a logged
  warning** (model, category, horizon, origin date, error, fallback model).
- Honesty guardrails: archived verification ≠ regenerated validation ≠ scenario projection (never merged).

## 6. Data model
13 tables: users, reporting_units, crime_categories, crime_monthly_data, crime_sources, data_versions,
audit_logs, model_runs, forecasts, forecast_actual_comparisons, validation_metrics,
category_stability_labels, drift_monitoring (see `database/schema.sql`). Storage is **long** format;
the entry UI uses a **wide** editable table (easier to type) that is normalised on save.

## 7. Architecture decision
**Chosen MVP: Streamlit + SQLite + pandas/numpy/statsmodels/scikit-learn/LightGBM + Plotly + openpyxl.**
Rationale: fastest to build and demo, runs Python forecasting directly, native spreadsheet editor
(`st.data_editor`), easy uploads/exports, few deployment bugs. Alternatives (Flask/Django; FastAPI+React;
Next.js full-stack) are heavier and are documented as the **production upgrade path** in `DEPLOYMENT.md`.

---

## Defense explanation — why this software strengthens the thesis
The thesis already produced a verified forecasting study. This software turns that study into an
**operational monitoring framework**, which is the defensible novelty:
- New official PHQ months can be **entered or imported** through a standardized 17-unit / 15-category template.
- **Official source provenance** (URL + PDF + SHA-256) is preserved for every month.
- **Data integrity** is checked automatically before anything enters the pipeline.
- **Forecast-vs-actual** comparison is automated; each new month becomes an out-of-sample test point.
- **Error metrics** (MAPE/sMAPE/MAE/RMSE/true_MASE/WAPE) update continuously.
- **Drift monitoring** flags when performance degrades and recommends action.
- **Rolling-origin validation** can be refreshed without leakage.
- The model is **recalibrated** and the **next forecast** is generated transparently.
- **Custom district/area** entries are supported but controlled so they cannot silently corrupt the
  validated 17-unit forecasting structure.
- Everything is **audit-logged**, and future projections are clearly **scenario-only**.

This directly realises the paper's "continuously updateable monitoring loop" claim as working software,
while keeping the verified-accuracy, rolling-origin-validation, and scenario-projection results strictly
separate and reviewer-safe.

## 8. Future research note (not in MVP)
Transformer / attention-based models are intentionally **excluded** from the MVP: at 76 monthly
observations they are not methodologically appropriate as a main model and were not competitive in the
thesis benchmark. They may be revisited once a much longer monthly (or unit-level panel) history exists.

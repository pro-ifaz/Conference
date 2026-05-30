-- PHQ Reported-Crime Monitoring System — SQLite schema
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, email TEXT, password TEXT, role TEXT,
  created_at TEXT, status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS reporting_units (
  unit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_name TEXT UNIQUE, unit_type TEXT,
  is_standard_phq_unit INTEGER DEFAULT 1,
  is_active INTEGER DEFAULT 1,
  mapped_to TEXT,                    -- standard unit a custom row maps to (NULL if none)
  created_by TEXT, created_at TEXT, note TEXT
);

CREATE TABLE IF NOT EXISTS crime_categories (
  category_id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_name TEXT UNIQUE, display_name TEXT,
  is_standard_phq_category INTEGER DEFAULT 1,
  is_model_supported INTEGER DEFAULT 1,
  is_active INTEGER DEFAULT 1,
  mapped_to TEXT,
  created_by TEXT, created_at TEXT, note TEXT
);

CREATE TABLE IF NOT EXISTS crime_monthly_data (
  data_id INTEGER PRIMARY KEY AUTOINCREMENT,
  year INTEGER, month INTEGER, date TEXT,
  police_unit TEXT, crime_category TEXT, value REAL,
  total_cases REAL, source_id INTEGER, version_id INTEGER,
  created_by TEXT, created_at TEXT, updated_at TEXT,
  verification_status TEXT DEFAULT 'draft',
  is_custom_unit INTEGER DEFAULT 0, is_custom_category INTEGER DEFAULT 0,
  in_model_pipeline INTEGER DEFAULT 1,   -- custom/unmapped rows excluded from pipeline
  is_active INTEGER DEFAULT 1,           -- only the latest approved active version is used
  custom_note TEXT
);

CREATE TABLE IF NOT EXISTS crime_sources (
  source_id INTEGER PRIMARY KEY AUTOINCREMENT,
  year INTEGER, month INTEGER, phq_url TEXT,
  pdf_filename TEXT, pdf_path TEXT, sha256_checksum TEXT,
  uploaded_by TEXT, uploaded_at TEXT,
  verification_status TEXT DEFAULT 'pending', reviewer_note TEXT,
  phq_statement_date TEXT
);

CREATE TABLE IF NOT EXISTS data_versions (
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  year INTEGER, month INTEGER, version_number INTEGER,
  status TEXT DEFAULT 'draft', created_by TEXT, created_at TEXT,
  approved_by TEXT, approved_at TEXT, change_summary TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT, record_id TEXT, action TEXT,
  old_value TEXT, new_value TEXT, changed_by TEXT, changed_at TEXT,
  reason TEXT, source_id INTEGER,
  affected_year INTEGER, affected_month INTEGER,
  affected_unit TEXT, affected_category TEXT, custom_field_flag INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS model_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT, dataset_version TEXT, cutoff_date TEXT,
  run_type TEXT, models_used TEXT, horizons TEXT,
  status TEXT, runtime_seconds REAL, notes TEXT
);

CREATE TABLE IF NOT EXISTS forecasts (
  forecast_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, forecast_origin TEXT, target_date TEXT, horizon INTEGER,
  police_unit_or_national TEXT, category TEXT, model_name TEXT,
  forecast_value REAL, lower_bound REAL, upper_bound REAL,
  is_scenario_projection INTEGER DEFAULT 0, created_at TEXT
);

CREATE TABLE IF NOT EXISTS forecast_actual_comparisons (
  comparison_id INTEGER PRIMARY KEY AUTOINCREMENT,
  forecast_id INTEGER, actual_date TEXT, actual_value REAL, forecast_value REAL,
  error REAL, absolute_error REAL, percentage_error REAL,
  smape_component REAL, category TEXT, compared_at TEXT
);

CREATE TABLE IF NOT EXISTS validation_metrics (
  metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, model_name TEXT, category TEXT, horizon INTEGER,
  MAPE REAL, sMAPE REAL, MAE REAL, RMSE REAL, true_MASE REAL, WAPE REAL,
  practical_accuracy REAL, sample_size INTEGER, created_at TEXT
);

CREATE TABLE IF NOT EXISTS category_stability_labels (
  label_id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT, stability_label TEXT, volatility_score REAL,
  mean_mape REAL, reason TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS drift_monitoring (
  drift_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, year INTEGER, month INTEGER, category TEXT,
  police_unit_or_national TEXT, recent_mape REAL, baseline_mape REAL,
  recent_mae REAL, baseline_mae REAL, recent_rmse REAL, baseline_rmse REAL,
  percentage_error_change REAL, actual_vs_forecast_deviation REAL,
  drift_status TEXT, recommendation TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS model_fallback_log (
  fallback_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, model_name TEXT, category TEXT, horizon INTEGER,
  forecast_origin TEXT, error_message TEXT, fallback_model TEXT, created_at TEXT
);

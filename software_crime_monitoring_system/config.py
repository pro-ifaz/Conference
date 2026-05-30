"""Central configuration: paths, standard PHQ schema, thresholds, initial seed users.

Production note (auth):
  - Passwords are stored hashed (scrypt) in the SQLite users table. See modules/auth.py.
  - On first run, the seed users below are inserted with their plaintext password
    and then immediately re-hashed by `auth.ensure_hashed_users` (called from `init_db`).
  - Set `PHQ_ADMIN_PASSWORD` in the environment to override the admin password without
    touching the DB (recovery / first-time deploy). Set `PHQ_AUTH_PEPPER` to a long random
    string in production so a leaked DB alone cannot be used to brute-force passwords.

Production note (models):
  - FAST_DEMO_MODE = False enables the full model set / horizon / category sweep.
  - Recalibration takes ~60-120 s on the seed dataset; run it after each monthly approval.
"""
import os
from pathlib import Path

APP_NAME = "PHQ Reported-Crime Monitoring System"
APP_TAGLINE = "Official PHQ reported-crime forecasting & monthly monitoring framework — Bangladesh"

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
PROCESSED = DATA / "processed"
UPLOADS = DATA / "uploaded_sources"
EXPORTS = DATA / "exports"
TEMPLATES = DATA / "templates"
DB_PATH = BASE / "database" / "crime_monitoring.db"
SCHEMA_SQL = BASE / "database" / "schema.sql"
OUTPUTS = BASE / "outputs"
# Ensure every writable directory exists on a fresh deploy (incl. DB dir + processed)
for p in (UPLOADS, EXPORTS, TEMPLATES, OUTPUTS, PROCESSED, DB_PATH.parent):
    p.mkdir(parents=True, exist_ok=True)

# --- Standard PHQ reporting structure (validated 17-unit forecasting dataset) ---
STANDARD_UNITS = [
    "DMP", "CMP", "KMP", "RMP", "BMP", "SMP", "RPMP", "GMP",
    "Dhaka Range", "Mymensingh Range", "Chittagong Range", "Sylhet Range",
    "Khulna Range", "Barishal Range", "Rajshahi Range", "Rangpur Range", "Railway Range",
]
UNIT_TYPE = {u: ("Metropolitan Police" if u not in (
    "Dhaka Range", "Mymensingh Range", "Chittagong Range", "Sylhet Range",
    "Khulna Range", "Barishal Range", "Rajshahi Range", "Rangpur Range", "Railway Range")
    else "Range") for u in STANDARD_UNITS}

# 15 official PHQ categories (order matters for Total_Cases = sum of all 15)
STANDARD_CATEGORIES = [
    "Dacoity", "Robbery", "Murder", "Speedy_Trial", "Riot", "Woman_Child_Repression",
    "Kidnapping", "Police_Assault", "Burglary", "Theft", "Other_Cases",
    "RC_Arms_Act", "RC_Explosive_Act", "RC_Narcotics", "RC_Smuggling",
]
RECOVERY_CATEGORIES = ["RC_Arms_Act", "RC_Explosive_Act", "RC_Narcotics", "RC_Smuggling"]

STABLE_CATEGORIES = ["Total_Cases", "Murder", "Theft", "Woman_Child_Repression", "Robbery"]
HARD_CATEGORIES = ["RC_Narcotics", "Kidnapping", "Dacoity"]

HORIZONS = [1, 3, 6, 12]

# --- Production mode: full model / horizon / category sweep ---
# Set PHQ_FAST_DEMO_MODE=1 in the environment to switch back to fast demo mode (~2 min).
FAST_DEMO_MODE = os.environ.get("PHQ_FAST_DEMO_MODE", "0").lower() in ("1", "true", "yes")

# Demo-only knobs (used iff FAST_DEMO_MODE is True; ignored in production)
DEMO_MODELS = ["SeasonalNaive", "Theta", "ARIMA", "LightGBM", "Ensemble"]
DEMO_ENSEMBLE_MEMBERS = ["SeasonalNaive", "Theta", "LightGBM"]
DEMO_HORIZONS = [1, 3, 6]
DEMO_MAX_FOLDS = 3
DEMO_CATEGORIES = ["Total_Cases", "Murder", "Theft", "Woman_Child_Repression", "Robbery", "RC_Narcotics"]
SEASONAL_PERIOD = 12
RANDOM_SEED = 42

# Per-model wall-clock cap (seconds). 20 s gives SARIMA enough headroom in production.
MODEL_TIMEOUT_SECONDS = int(os.environ.get("PHQ_MODEL_TIMEOUT", "20"))

# Rolling-origin config
INITIAL_TRAIN_MONTHS = 36
CV_STEP = 6
MAX_FOLDS = 5

# Drift thresholds (relative MAPE increase vs baseline)
DRIFT_WARNING_RATIO = 1.25
DRIFT_CRITICAL_RATIO = 1.60
DRIFT_DEVIATION_WARN = 0.15

# Initial seed users (inserted ONCE on a fresh DB, then immediately re-hashed by auth.py).
DEMO_USERS = {
    "admin":    {"password": "admin123",   "role": "admin",    "name": "System Admin"},
    "operator": {"password": "operator123","role": "operator", "name": "Data Entry Operator"},
    "reviewer": {"password": "reviewer123","role": "reviewer", "name": "Reviewer"},
    "viewer":   {"password": "viewer123",  "role": "viewer",   "name": "Viewer"},
}
ROLE_PERMS = {
    "admin":    {"enter", "import", "validate", "approve", "recalibrate", "view"},
    "operator": {"enter", "import", "validate", "view"},
    "reviewer": {"validate", "approve", "view"},
    "viewer":   {"view"},
}

# Show the seed-credentials hint on the login page? Off in production.
SHOW_LOGIN_HINT = os.environ.get("PHQ_SHOW_LOGIN_HINT", "0").lower() in ("1", "true", "yes")

# Refuse user-entered scenario horizons beyond this many months past the latest observation.
MAX_SCENARIO_HORIZON_MONTHS = 36

PRACTICAL_ACCURACY_NOTE = (
    "practical_accuracy = 100 − MAPE is a readability convention, not a probability of being correct. "
    "MAPE and true_MASE are the primary error metrics."
)
SCENARIO_WARNING = (
    "⚠️ SCENARIO PROJECTION ONLY — not verified accuracy, not ground truth, not a validated prediction. "
    "The system forecasts officially reported-crime counts, not hidden or unreported crime."
)

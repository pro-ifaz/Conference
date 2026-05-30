"""Smoke checks (A–E) for the PHQ monitoring MVP. Run:  python tests/smoke_check.py
Small and explainable — not a full test framework. Uses a temporary DB copy so it never
touches your real database/crime_monitoring.db."""
import os
import sys
import shutil
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config as C  # noqa: E402

# redirect the DB to a temp file so checks are isolated
_tmp = Path(tempfile.gettempdir()) / "phq_smoke_check.db"
if _tmp.exists():
    _tmp.unlink()
C.DB_PATH = _tmp

from modules import db, data_entry as DE, recalibration as R, forecasting as F  # noqa: E402
import pandas as pd  # noqa: E402

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

# ---- A. seed loads: 88 months, 17 units ----
db.init_db()
nat = db.national_series("Total_Cases")
units = db.list_units()
check("A. seed 88 months", len(nat) == 88, f"{len(nat)} months")
check("A. seed 17 PHQ units", units.shape[0] == 17, f"{units.shape[0]} units")
base_total_apr26 = float(nat.loc[pd.Timestamp("2026-04-01")]) if pd.Timestamp("2026-04-01") in nat.index else None
check("A. April 2026 present", base_total_apr26 is not None, f"Total_Cases={base_total_apr26}")

# ---- B. duplicate month safety: re-enter + approve April 2026 again, totals must not double ----
wide = (db.long_table().query("year==2026 and month==4")
        .pivot_table(index="police_unit", columns="crime_category", values="value", aggfunc="first")
        .reset_index().rename(columns={"police_unit": "Unit"}))
DE.save_month(wide, 2026, 4, "smoke", status="submitted")   # new version of same month
DE.approve_month(2026, 4, "smoke")                          # approve latest, deactivate old
nat2 = db.national_series("Total_Cases")
after_total_apr26 = float(nat2.loc[pd.Timestamp("2026-04-01")])
check("B. April 2026 not doubled", abs(after_total_apr26 - base_total_apr26) < 1e-6,
      f"before={base_total_apr26}, after={after_total_apr26}")
check("B. month count unchanged", len(nat2) == 88, f"{len(nat2)} months")

# ---- C. forecasting finishes (LightGBM does not hang) ----
import time
t0 = time.time()
s = db.national_series("Murder")
out = F.predict("LightGBM", s.values[:60], 3, "Murder", "smoke")
dt = time.time() - t0
check("C. LightGBM forecast finishes", len(out) == 3 and dt < 30, f"{dt:.1f}s, len={len(out)}")

# ---- D + E. recalibration persists saved forecasts; forecast-vs-actual uses them ----
res = R.recalibrate(created_by="smoke")
conn = db.get_conn()
n_fc = pd.read_sql_query("SELECT COUNT(*) n FROM forecasts", conn).iloc[0]["n"]
n_cmp = pd.read_sql_query("SELECT COUNT(*) n FROM forecast_actual_comparisons", conn).iloc[0]["n"]
n_drift = pd.read_sql_query("SELECT COUNT(*) n FROM drift_monitoring", conn).iloc[0]["n"]
n_stab = pd.read_sql_query("SELECT COUNT(*) n FROM category_stability_labels", conn).iloc[0]["n"]
n_metric = pd.read_sql_query("SELECT COUNT(*) n FROM validation_metrics", conn).iloc[0]["n"]
# E: a saved forecast exists whose target month has an approved actual
saved = pd.read_sql_query(
    "SELECT category,target_date,forecast_value FROM forecasts "
    "WHERE is_scenario_projection=0 AND category='Total_Cases'", conn)
conn.close()
check("D. recalibration saved forecast rows", n_fc > 0, f"{n_fc} forecast rows")
check("D. recalibration saved comparison rows", n_cmp > 0, f"{n_cmp} comparison rows")
check("D. recalibration saved drift rows", n_drift > 0, f"{n_drift} drift rows")
check("D. recalibration saved stability + metrics", n_stab > 0 and n_metric > 0,
      f"{n_stab} stability, {n_metric} metric rows")
saved["target_date"] = pd.to_datetime(saved["target_date"])
matched = saved[saved["target_date"].isin(nat2.index)]
check("E. forecast-vs-actual has saved forecast for an approved month", len(matched) > 0,
      f"{len(matched)} matchable saved Total_Cases forecasts")

# ---- F. Dashboard/Model Metrics can read persisted rows via a FRESH connection (restart-safe) ----
run_row = db.latest_run()
vm = db.latest_validation_metrics()
drift = db.latest_drift_status()
check("F. latest_run readable from DB", run_row is not None, f"run_id={run_row and run_row.get('run_id')}")
check("F. validation_metrics readable from DB", not vm.empty, f"{len(vm)} metric rows")
check("F. drift status readable from DB", drift is not None, f"status={drift}")

# ---- G. Auth: passwords hashed at init, seed login works, wrong pw rejected, lockout fires ----
from modules import auth  # noqa: E402
import sqlite3 as _sql3  # noqa: E402
conn_a = _sql3.connect(C.DB_PATH); conn_a.row_factory = _sql3.Row
pw_rows = conn_a.execute("SELECT password FROM users").fetchall()
all_hashed = all((r["password"] or "").startswith("scrypt$") for r in pw_rows)
check("G. user passwords hashed at init", all_hashed, f"{len(pw_rows)} users")
rec_admin = auth.authenticate(conn_a, "admin", "admin123")
check("G. admin login with seed password", rec_admin is not None and rec_admin["role"] == "admin")
rec_bad = auth.authenticate(conn_a, "admin", "wrong-pw")
check("G. wrong password rejected", rec_bad is None)
state_l = {}
for _ in range(auth.LOCKOUT_MAX_FAILS):
    auth.record_failure(state_l, "admin")
check("G. lockout triggers after MAX_FAILS", auth.is_locked(state_l, "admin")[0])
conn_a.close()

# summary
n_pass = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 50)
print(f"SMOKE CHECK: {n_pass}/{len(results)} passed")
if _tmp.exists():
    _tmp.unlink()
sys.exit(0 if n_pass == len(results) else 1)

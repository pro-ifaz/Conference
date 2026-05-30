"""Regression tests for the two reported bugs + bonus hardening.

Covers:
  1. validate_wide is crash-proof against NaN / numeric / blank / duplicate units and odd
     category headers (the original 'expected str instance, float found' TypeError).
  2. validate_wide produces no false failures on a clean full month.
  3. clean_uploaded_wide drops junk rows and reports what it did.
  4. save_month never persists a blank-unit row.
  5. delete_month (soft) deactivates a month and it disappears from the active series;
     restore_month brings it back with totals intact and no double counting.
  6. delete_month (hard) physically removes a month; restore then fails cleanly.
  7. Guard rails: empty reason / non-existent month raise ValueError.

Run:  python tests/test_fixes.py   (uses an isolated temp DB)
"""
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config as C  # noqa: E402
_tmp = Path(tempfile.gettempdir()) / "phq_test_fixes.db"
if _tmp.exists():
    _tmp.unlink()
C.DB_PATH = _tmp

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from modules import db, data_entry as DE, validation as V  # noqa: E402

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

db.init_db()
existing = set((int(r.year), int(r.month)) for _, r in db.months_present().iterrows())
cats = C.STANDARD_CATEGORIES


def _full_clean_wide():
    rows = [[u] + [1] * len(cats) for u in C.STANDARD_UNITS]
    df = pd.DataFrame(rows, columns=["Unit"] + cats)
    return DE.autocalc_total(df).set_index("Unit")


# ---- 1. crash-proof validation on the exact failing shapes -------------------
poison = _full_clean_wide().reset_index()
poison.loc[len(poison)] = [np.nan] + [0] * (poison.shape[1] - 1)     # NaN (float) unit
poison.loc[len(poison)] = [2024] + [0] * (poison.shape[1] - 1)       # numeric unit
poison.loc[len(poison)] = ["   "] + [0] * (poison.shape[1] - 1)      # whitespace unit
poison.loc[len(poison)] = ["DMP"] + [0] * (poison.shape[1] - 1)      # duplicate of DMP
poison_wide = poison.set_index("Unit")
try:
    rep = V.validate_wide(poison_wide, 2026, 5, existing, None)
    crashed = False
except TypeError as e:
    crashed = True
    rep = None
check("1. validate_wide no longer raises TypeError", not crashed,
      "" if not crashed else "still crashing")
if rep is not None:
    check("1. blank unit reported", rep["summary"]["n_blank_units"] >= 2,
          f"n_blank_units={rep['summary']['n_blank_units']}")
    check("1. duplicate unit reported", rep["summary"]["n_duplicate_units"] == 1,
          f"n_duplicate_units={rep['summary']['n_duplicate_units']}")
    check("1. cannot approve poisoned month", rep["can_approve"] is False)

# numeric/whitespace CATEGORY headers must not crash the join either
weird = _full_clean_wide().reset_index()
weird[2099] = 0                 # numeric column header
weird["  Spare  "] = 0          # whitespace custom header
try:
    rep_w = V.validate_wide(weird.set_index("Unit"), 2026, 5, existing, None)
    check("1b. odd category headers handled", True,
          f"extra_cats={rep_w['summary']['extra_cats']}")
except Exception as e:
    check("1b. odd category headers handled", False, str(e))

# ---- 2. no false failures on a clean full month -----------------------------
clean_rep = V.validate_wide(_full_clean_wide(), 2026, 5, existing, None)
check("2. clean month has zero failures", len(clean_rep["failed"]) == 0,
      f"failed={clean_rep['failed']}")
check("2. clean month can_approve", clean_rep["can_approve"] is True)

# ---- 3. clean_uploaded_wide hygiene -----------------------------------------
dirty = _full_clean_wide().reset_index()
dirty.loc[len(dirty)] = [np.nan] * dirty.shape[1]                    # fully empty row
dirty.loc[len(dirty)] = ["  "] + [5] * (dirty.shape[1] - 1)          # blank-name row
dirty.loc[len(dirty)] = [3030] + [7] * (dirty.shape[1] - 1)          # numeric unit -> '3030'
dirty.loc[len(dirty)] = ["DMP"] + [9] * (dirty.shape[1] - 1)         # duplicate
cleaned, report = DE.clean_uploaded_wide(dirty)
check("3. empty row dropped", report["empty_rows_dropped"] == 1, str(report))
check("3. blank-unit row dropped", report["blank_unit_rows_dropped"] == 1, str(report))
check("3. numeric unit normalised to string", "3030" in set(cleaned["Unit"]),
      f"units sample={sorted(set(cleaned['Unit']))[:3]}")
check("3. duplicate reported", "DMP" in report["duplicate_units"], str(report["duplicate_units"]))

# ---- 4. save_month skips blank-unit rows ------------------------------------
blanky = _full_clean_wide().reset_index()
blanky.loc[len(blanky)] = [np.nan] + [3] * (blanky.shape[1] - 1)
DE.save_month(blanky, 2030, 1, "tester", status="submitted")
conn = db.get_conn()
n_blank_persisted = conn.execute(
    "SELECT COUNT(*) FROM crime_monthly_data WHERE year=2030 AND month=1 "
    "AND (police_unit IS NULL OR TRIM(police_unit)='' OR police_unit='nan')").fetchone()[0]
n_units_persisted = conn.execute(
    "SELECT COUNT(DISTINCT police_unit) FROM crime_monthly_data WHERE year=2030 AND month=1").fetchone()[0]
conn.close()
check("4. no blank-unit row persisted", n_blank_persisted == 0, f"{n_blank_persisted} blank rows")
check("4. exactly 17 units persisted", n_units_persisted == 17, f"{n_units_persisted} units")

# ---- 5. soft delete + restore (April 2026 from the seed) --------------------
nat0 = db.national_series("Total_Cases")
apr = pd.Timestamp("2026-04-01")
base_apr = float(nat0.loc[apr])
base_n = len(nat0)

DE.delete_month(2026, 4, "tester", reason="bad source — re-importing")
db.invalidate_cache()
nat1 = db.national_series("Total_Cases")
mgmt = db.month_management_table()
state_apr = mgmt.query("year==2026 and month==4")["state"].iloc[0]
present_after_delete = ((db.months_present()["year"] == 2026) &
                        (db.months_present()["month"] == 4)).any()
check("5. soft delete removes month from active series", apr not in nat1.index,
      f"len {base_n} -> {len(nat1)}")
check("5. soft delete: not in months_present", not present_after_delete)
check("5. soft delete: shows as 'deleted (soft)'", state_apr == "deleted (soft)", state_apr)

DE.restore_month(2026, 4, "tester", reason="false alarm")
db.invalidate_cache()
nat2 = db.national_series("Total_Cases")
check("5. restore brings month back", apr in nat2.index, f"len now {len(nat2)}")
check("5. restore preserves total (no double count)", abs(float(nat2.loc[apr]) - base_apr) < 1e-6,
      f"before={base_apr}, after={float(nat2.loc[apr])}")
check("5. restore keeps month count stable", len(nat2) == base_n, f"{len(nat2)} vs {base_n}")

# ---- 6. hard delete is permanent; restore then fails ------------------------
DE.delete_month(2026, 4, "tester", reason="purge for good", hard=True)
db.invalidate_cache()
conn = db.get_conn()
rows_left = conn.execute("SELECT COUNT(*) FROM crime_monthly_data WHERE year=2026 AND month=4").fetchone()[0]
conn.close()
check("6. hard delete removes all rows", rows_left == 0, f"{rows_left} rows left")
try:
    DE.restore_month(2026, 4, "tester")
    check("6. restore after hard delete raises", False, "did not raise")
except ValueError:
    check("6. restore after hard delete raises", True)

# ---- 7. guard rails ---------------------------------------------------------
try:
    DE.delete_month(2025, 1, "tester", reason="")
    check("7. empty reason rejected", False, "did not raise")
except ValueError:
    check("7. empty reason rejected", True)
try:
    DE.delete_month(1900, 1, "tester", reason="nope")
    check("7. non-existent month rejected", False, "did not raise")
except ValueError:
    check("7. non-existent month rejected", True)

# summary
n_pass = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 56)
print(f"FIX TESTS: {n_pass}/{len(results)} passed")
if _tmp.exists():
    _tmp.unlink()
sys.exit(0 if n_pass == len(results) else 1)

"""Headless Streamlit UI test for pages/2_Add_Monthly_Data.py using AppTest.

Verifies the actual page wiring (no browser):
  - the page renders without raising for a logged-in admin
  - the Manage/Delete section (Section 6) is present for an admin
  - a soft delete via the real buttons/inputs deactivates a month
  - the deleted month then shows as restorable and a restore brings it back
  - an operator (no 'delete' perm) does NOT see the delete controls

Run:  python tests/test_page_appui.py   (isolated temp DB)
"""
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config as C  # noqa: E402
_tmp = Path(tempfile.gettempdir()) / "phq_test_pageui.db"
if _tmp.exists():
    _tmp.unlink()
C.DB_PATH = _tmp

from modules import db  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

db.init_db()  # seed 88 months / 17 units into the temp DB
PAGE = str(ROOT / "pages" / "2_Add_Monthly_Data.py")

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _run_as(role, name, username):
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user"] = {"username": username, "name": name, "role": role, "source": "test"}
    at.session_state["_phq_page_config_done"] = False
    return at.run()


def _find_button(at, label_substr):
    for b in at.button:
        if label_substr.lower() in (b.label or "").lower():
            return b
    return None


def _set_text(at, key, value):
    for t in at.text_input:
        if t.key == key:
            t.set_value(value)
            return True
    return False


# ---- admin: page renders, delete section present ----------------------------
at = _run_as("admin", "System Admin", "admin")
check("admin: page runs without exception", not at.exception,
      str(at.exception) if at.exception else "")
all_md = " ".join(m.value for m in at.markdown)
check("admin: Section 6 present", "Manage / delete existing months" in all_md
      or "Delete or restore a month" in all_md)
check("admin: delete button present", _find_button(at, "Delete month") is not None)

# ---- operator: no delete controls (lacks 'delete' permission) ---------------
at_op = _run_as("operator", "Operator", "operator")
check("operator: page runs without exception", not at_op.exception,
      str(at_op.exception) if at_op.exception else "")
op_md = " ".join(m.value for m in at_op.markdown)
check("operator: NO delete section", "Delete or restore a month" not in op_md)
check("operator: NO delete button", _find_button(at_op, "Delete month") is None)

# ---- admin soft-delete flow via real widgets --------------------------------
nat_before = len(db.national_series("Total_Cases"))
at = _run_as("admin", "System Admin", "admin")
# choose a month known to exist in the seed
target = None
for sb in at.selectbox:
    if sb.key == "mng_sel":
        for o in sb.options:
            if o.startswith("2025-12"):
                target = o
                break
        if target:
            sb.set_value(target)
        break
at = at.run()
token = "2025-12"
ok_reason = _set_text(at, "mng_del_reason", "unit-test soft delete")
ok_conf = _set_text(at, "mng_del_confirm", f"DELETE {token}")
at = at.run()
btn = _find_button(at, "Delete month")
check("admin: delete inputs settable", ok_reason and ok_conf)
if btn is not None:
    btn.click()
    at = at.run()
db.invalidate_cache()
nat_after = len(db.national_series("Total_Cases"))
mgmt = db.month_management_table()
state = mgmt.query("year==2025 and month==12")["state"].iloc[0]
check("admin: soft delete removed a month from active series",
      nat_after == nat_before - 1, f"{nat_before} -> {nat_after}")
check("admin: month now 'deleted (soft)'", state == "deleted (soft)", state)
check("admin: page still healthy after delete", not at.exception,
      str(at.exception) if at.exception else "")

# ---- admin restore flow -----------------------------------------------------
at = _run_as("admin", "System Admin", "admin")
for sb in at.selectbox:
    if sb.key == "mng_sel":
        for o in sb.options:
            if o.startswith("2025-12") and "deleted" in o:
                sb.set_value(o)
                break
        break
at = at.run()
_set_text(at, "mng_restore_confirm", f"RESTORE {token}")
at = at.run()
rbtn = _find_button(at, "Restore month")
check("admin: restore button appears for soft-deleted month", rbtn is not None)
if rbtn is not None:
    rbtn.click()
    at = at.run()
db.invalidate_cache()
nat_restored = len(db.national_series("Total_Cases"))
check("admin: restore brought the month back", nat_restored == nat_before,
      f"{nat_after} -> {nat_restored}")

# summary
n_pass = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 56)
print(f"PAGE UI TESTS: {n_pass}/{len(results)} passed")
if _tmp.exists():
    _tmp.unlink()
sys.exit(0 if n_pass == len(results) else 1)

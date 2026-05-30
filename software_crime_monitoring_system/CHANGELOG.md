# Changelog — QA & hardening pass (2026-05)

This release fixes two reported defects and several related issues found during a full
QA review of the data-ingestion and data-lifecycle paths. All changes are covered by
automated tests (`tests/`), and the existing smoke suite still passes 18/18.

## Fixed

### 1. Upload crash — `TypeError: sequence item N: expected str instance, float found`
**Where:** `modules/validation.py` → `validate_wide` (the `", ".join(extra_units)` calls).

**Cause:** A blank or numeric `Unit` cell in an uploaded `.xlsx`/CSV (a trailing total row,
a merged-cell artefact, or a stray number) was read by pandas as a `NaN`/float and placed
in the dataframe index. `str.join` cannot join a non-string, so validation crashed before
the user could see any result.

**Fix (defence in depth):**
- `validate_wide` is now crash-proof. Blank/`NaN` units, numeric units, **and** non-string
  category headers (a numeric or whitespace column name would have triggered the same crash —
  a latent bug on the `extra_cats` join) are all coerced safely for display.
- Blank-unit rows and **duplicate unit rows** (which would silently double-count a unit for
  the month) are now reported as explicit validation **failures** that block approval, instead
  of crashing or passing through unnoticed.
- New sanitiser `data_entry.clean_uploaded_wide()` runs on every import: it drops fully-empty
  rows, normalises unit labels (`2024.0 → "2024"`, trims whitespace), removes blank-name rows,
  and reports duplicates. The Add Monthly Data page shows a "🧹 Auto-cleaned on import" summary
  so nothing is removed silently.
- `data_entry.save_month()` will no longer persist a blank/`NaN` unit row even if one slips
  through, and notes any skipped rows in the audit log.

### 2. No way to delete monthly data (only add)
**Where:** `modules/data_entry.py`, `modules/db.py`, `pages/2_Add_Monthly_Data.py`.

A full, auditable month-deletion lifecycle was added:
- **Soft delete** (default, reversible): deactivates the month so it disappears from all
  forecasts and dashboards while the data is retained. Recommended for correcting a bad import.
- **Restore**: reverses a soft delete, reactivating exactly **one** version so national totals
  can never double-count (mirrors `approve_month`).
- **Hard delete** (admin only, permanent): physically purges the month's rows and version
  records; pre-delete totals are captured in the audit log for traceability.
- New **"Section 6 · Manage / delete existing months"** UI panel: month inventory table,
  type-to-confirm boxes (`DELETE 2026-02` / `RESTORE 2026-02`), a required reason, a warning
  when deleting a non-latest month (time-series gap), and a one-click recalibration offer
  afterwards so forecasts/drift stay consistent.
- New `delete` permission added to the **admin** role only (`config.ROLE_PERMS`); a permanent
  hard delete is further gated to admins at the UI layer. Operators/reviewers/viewers do not
  see the delete controls.

## Tests added
- `tests/test_fixes.py` — 23 checks: validation crash-proofing (NaN/numeric/blank/duplicate
  units, odd headers), no false failures on a clean month, import sanitiser behaviour,
  blank-row save guard, and the soft-delete / restore / hard-delete lifecycle incl. guard rails.
- `tests/test_page_appui.py` — 12 checks using Streamlit's `AppTest`: the page renders for an
  admin, the delete panel is present for admins and absent for operators, and a soft delete +
  restore performed through the real on-screen widgets behave correctly.

Run them with:
```
python tests/smoke_check.py
python tests/test_fixes.py
python tests/test_page_appui.py
```

## Notes / not changed
- Streamlit deprecates `use_container_width` in favour of `width=` (removal is scheduled in a
  future release). This pattern is used across all 13 page files and `utils/ui.py`; it still
  works on current Streamlit and was left as-is to keep this fix focused. A separate cleanup
  pass is recommended before the parameter is removed.

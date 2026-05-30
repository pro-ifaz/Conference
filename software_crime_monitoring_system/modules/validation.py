"""Monthly data validation: structure, totals, anomalies, custom-field control."""
import numpy as np
import pandas as pd
import config as C


def validate_wide(df_wide: pd.DataFrame, year: int, month: int,
                  existing_months: set, prev_national: dict | None = None):
    """df_wide: index=unit, columns=categories (+optional Total_Cases).
    Returns dict with passed[], failed[], warnings[], summary{}."""
    passed, failed, warnings = [], [], []

    def _is_blank(v) -> bool:
        """A unit/category label is 'blank' if it is NaN/None or an empty/whitespace string.
        Upstream Excel exports frequently leave a trailing total row or merged-cell artefact
        that pandas reads as NaN (a float), so we must treat those explicitly rather than
        letting them reach str.join()."""
        if v is None:
            return True
        if isinstance(v, float) and np.isnan(v):
            return True
        return str(v).strip() == ""

    def _label(v) -> str:
        """Render any label (str / int / float) safely for a human-readable message."""
        if isinstance(v, float) and float(v).is_integer():
            return str(int(v))
        return str(v).strip()

    raw_units = list(df_wide.index)
    raw_cols = list(df_wide.columns)

    # --- blank / non-string unit rows (the classic 'expected str, float found' trigger) ---
    n_blank_units = sum(1 for u in raw_units if _is_blank(u))
    if n_blank_units:
        failed.append(f"{n_blank_units} row(s) have a blank/missing unit name "
                      "(usually a trailing total row or empty row — remove or label them).")

    # --- duplicate unit rows would double-count a unit for the month ---
    seen, dup_units = set(), []
    for u in raw_units:
        if _is_blank(u):
            continue
        key = _label(u)
        if key in seen and key not in dup_units:
            dup_units.append(key)
        seen.add(key)
    if dup_units:
        failed.append(f"Duplicate unit row(s) — would double-count: {', '.join(dup_units)}.")

    # named units/categories only (blanks handled above, so joins below can never crash)
    units = [_label(u) for u in raw_units if not _is_blank(u)]
    cats = [_label(c) for c in raw_cols if c != "Total_Cases" and not _is_blank(c)]

    # month duplication
    if (year, month) in existing_months:
        warnings.append(f"Month {year}-{month:02d} already exists — this would create a new version.")
    else:
        passed.append("Month does not already exist.")

    # standard units present
    missing_units = [u for u in C.STANDARD_UNITS if u not in units]
    extra_units = [u for u in units if u not in C.STANDARD_UNITS]
    if missing_units:
        failed.append(f"Missing required PHQ units ({len(missing_units)}): {', '.join(missing_units)}")
    else:
        passed.append("All 17 standard PHQ reporting units present.")
    if extra_units:
        warnings.append(f"Custom/non-standard units present: {', '.join(extra_units)} "
                        "(must be mapped or they are excluded from the model pipeline).")

    # standard categories present
    missing_cats = [c for c in C.STANDARD_CATEGORIES if c not in cats]
    extra_cats = [c for c in cats if c not in C.STANDARD_CATEGORIES]
    if missing_cats:
        failed.append(f"Missing required PHQ categories: {', '.join(missing_cats)}")
    else:
        passed.append("All 15 standard PHQ crime categories present.")
    if extra_cats:
        warnings.append(f"Custom categories present: {', '.join(extra_cats)} "
                        "(tracked + excluded from pipeline unless mapped).")

    # ---- numeric / negative / missing (built on a clean per-category frame) ----
    # Map each raw column -> cleaned label; skip blanks and Total_Cases; keep the first
    # occurrence if a category label is duplicated. Restrict to non-blank-unit rows so the
    # crash-trigger rows above are not double-counted here.
    row_keep = np.array([not _is_blank(u) for u in raw_units], dtype=bool)
    num_data = {}
    for raw_c in raw_cols:
        if raw_c == "Total_Cases" or _is_blank(raw_c):
            continue
        lbl = _label(raw_c)
        if lbl in num_data:
            continue  # duplicate category column → keep first
        col = df_wide[raw_c]
        if isinstance(col, pd.DataFrame):  # duplicate raw header → take first sub-column
            col = col.iloc[:, 0]
        num_data[lbl] = pd.to_numeric(col, errors="coerce")
    num = pd.DataFrame(num_data, index=df_wide.index)
    if len(num) and not row_keep.all():
        num = num[row_keep]

    n_missing = int(num.isna().sum().sum()) if num.size else 0
    n_negative = int((num < 0).sum().sum()) if num.size else 0
    failed.append(f"{n_missing} missing/non-numeric cells.") if n_missing else passed.append("No missing/non-numeric values.")
    failed.append(f"{n_negative} negative values (impossible for counts).") if n_negative else passed.append("No negative values.")

    # Total_Cases == sum of standard categories (per unit)
    std_present = [c for c in C.STANDARD_CATEGORIES if c in num.columns]
    rowsum = num[std_present].sum(axis=1) if std_present else pd.Series(0.0, index=num.index)
    mismatch = 0
    if "Total_Cases" in raw_cols:
        tc = df_wide["Total_Cases"]
        if isinstance(tc, pd.DataFrame):
            tc = tc.iloc[:, 0]
        given = pd.to_numeric(tc, errors="coerce")
        if len(given) and not row_keep.all():
            given = given[row_keep]
        mismatch = int((np.abs(given - rowsum) > 0.5).sum())
        if mismatch:
            warnings.append(f"{mismatch} unit(s) have Total_Cases ≠ sum of 15 categories "
                            "(auto-calc recommended).")
        else:
            passed.append("Total_Cases equals sum of categories for all units.")

    # extreme change vs previous month (national)
    nat_now = float(rowsum.sum())
    if prev_national:
        pv = prev_national.get("Total_Cases")
        if pv:
            chg = (nat_now - pv) / pv * 100
            if abs(chg) > 25:
                warnings.append(f"National Total_Cases changed {chg:+.1f}% vs previous month "
                                "(unusually large — verify source).")
            else:
                passed.append(f"National change vs previous month is {chg:+.1f}% (within normal range).")

    summary = dict(n_units=len(units), missing_units=len(missing_units), extra_units=len(extra_units),
                   missing_cats=len(missing_cats), extra_cats=len(extra_cats),
                   n_blank_units=int(n_blank_units), n_duplicate_units=len(dup_units),
                   n_missing=n_missing, n_negative=n_negative, total_mismatch_rows=mismatch,
                   national_total=nat_now, n_failed=len(failed))
    return dict(passed=passed, failed=failed, warnings=warnings, summary=summary,
                can_approve=(len(failed) == 0))

"""Monthly data validation: structure, totals, anomalies, custom-field control."""
import numpy as np
import pandas as pd
import config as C


def validate_wide(df_wide: pd.DataFrame, year: int, month: int,
                  existing_months: set, prev_national: dict | None = None):
    """df_wide: index=unit, columns=categories (+optional Total_Cases).
    Returns dict with passed[], failed[], warnings[], summary{}."""
    passed, failed, warnings = [], [], []
    units = list(df_wide.index)
    cats = [c for c in df_wide.columns if c != "Total_Cases"]

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

    # numeric / negative / missing
    num = df_wide[cats].apply(pd.to_numeric, errors="coerce")
    n_missing = int(num.isna().sum().sum())
    n_negative = int((num < 0).sum().sum())
    failed.append(f"{n_missing} missing/non-numeric cells.") if n_missing else passed.append("No missing/non-numeric values.")
    failed.append(f"{n_negative} negative values (impossible for counts).") if n_negative else passed.append("No negative values.")

    # Total_Cases == sum of standard categories (per unit)
    std_present = [c for c in C.STANDARD_CATEGORIES if c in num.columns]
    rowsum = num[std_present].sum(axis=1)
    mismatch = 0
    if "Total_Cases" in df_wide.columns:
        given = pd.to_numeric(df_wide["Total_Cases"], errors="coerce")
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
                   n_missing=n_missing, n_negative=n_negative, total_mismatch_rows=mismatch,
                   national_total=nat_now, n_failed=len(failed))
    return dict(passed=passed, failed=failed, warnings=warnings, summary=summary,
                can_approve=(len(failed) == 0))

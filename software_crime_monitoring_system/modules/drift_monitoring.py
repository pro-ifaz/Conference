"""Drift monitoring connected to the monthly feedback loop."""
import numpy as np
import pandas as pd
import config as C


def assess_drift(recent_mape, baseline_mape, deviation=None):
    """Return (status, recommendation) from recent vs baseline MAPE and optional deviation."""
    if baseline_mape is None or baseline_mape <= 0 or recent_mape is None or np.isnan(recent_mape):
        return "unknown", "insufficient history — keep model, collect more months"
    ratio = recent_mape / baseline_mape
    dev_alert = deviation is not None and deviation > C.DRIFT_DEVIATION_WARN
    if ratio >= C.DRIFT_CRITICAL_RATIO:
        return "critical", "recalibrate and review source data"
    if ratio >= C.DRIFT_WARNING_RATIO or dev_alert:
        return "warning", "recalibrate / monitor next month"
    return "normal", "keep model"


def window_drift(errs_pct, recent_n=3):
    """Explainable MVP drift from a time-ordered list of monthly abs% errors.
    baseline = mean of the EARLIER window, recent = mean of the LAST `recent_n` months.
    Returns (recent_mape, baseline_mape, pct_change, status, recommendation)."""
    e = [x for x in errs_pct if x is not None and not np.isnan(x)]
    if len(e) < recent_n + 2:
        return (np.nan, np.nan, None, "unknown",
                "insufficient forecast-vs-actual history — keep model, collect more months")
    recent = float(np.mean(e[-recent_n:]))
    baseline = float(np.mean(e[:-recent_n]))
    status, rec = assess_drift(recent, baseline)
    pct = round((recent - baseline) / baseline * 100, 1) if baseline > 0 else None
    return round(recent, 2), round(baseline, 2), pct, status, rec


def category_drift(cv_recent: pd.DataFrame, cv_baseline: pd.DataFrame, categories):
    """Compare per-category 1-month MAPE between a recent run and a baseline run.
    Returns one row per category with status + recommendation."""
    def m1(df, cat):
        sub = df[(df.category == cat) & (df.horizon == 1)]
        return float(sub["MAPE"].min()) if len(sub) else np.nan
    rows = []
    for cat in categories:
        r, b = m1(cv_recent, cat), m1(cv_baseline, cat)
        status, rec = assess_drift(r, b)
        rows.append(dict(category=cat, recent_mape=round(r, 2) if not np.isnan(r) else None,
                         baseline_mape=round(b, 2) if not np.isnan(b) else None,
                         pct_change=(round((r - b) / b * 100, 1) if b and not np.isnan(r) and not np.isnan(b) else None),
                         drift_status=status, recommendation=rec))
    return pd.DataFrame(rows)

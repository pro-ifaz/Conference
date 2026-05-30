"""Model recalibration: refresh validation, drift, stability, store a run, generate next forecast."""
import time
import json
import numpy as np
import pandas as pd
import config as C
from .db import get_conn, national_series, _now
from . import forecasting as F
from . import drift_monitoring as D


def recalibrate(run_type="recalibration", created_by="system"):
    """Reload data → rolling-origin per category → best-model selection → drift → stability →
    next forecast. Returns a dict of results. Stores a model_run + metrics + forecasts + drift."""
    t0 = time.time()
    F.FALLBACK_LOG.clear()
    F.clear_cache()
    demo = getattr(C, "FAST_DEMO_MODE", False)
    cats = (C.DEMO_CATEGORIES if demo else (C.STABLE_CATEGORIES + C.HARD_CATEGORIES))
    rmodels = C.DEMO_MODELS if demo else None
    rhoriz = C.DEMO_HORIZONS if demo else C.HORIZONS
    rfolds = C.DEMO_MAX_FOLDS if demo else C.MAX_FOLDS
    cv_all = []
    series_map = {}
    for c in cats:
        s = national_series(c, approved_only=True)
        if len(s) < C.INITIAL_TRAIN_MONTHS + 1:
            continue
        series_map[c] = s
        cv_all.append(F.rolling_origin(s, category=c, models=rmodels,
                                       horizons=rhoriz, max_folds=rfolds))
    cv = pd.concat(cv_all, ignore_index=True) if cv_all else pd.DataFrame()
    best = F.best_model_per_cell(cv)

    # stability labels (volatility = std/mean of last 24 months; mean MAPE at h=1 best)
    stab = []
    for c in cats:
        if c not in series_map:
            continue
        s = series_map[c]
        vol = float(np.std(s.values[-24:]) / (np.mean(s.values[-24:]) + 1e-9))
        m1 = best[(best.category == c) & (best.horizon == 1)]["MAPE"]
        m1 = float(m1.iloc[0]) if len(m1) else np.nan
        label = "stable" if c in C.STABLE_CATEGORIES else "hard"
        # drift-aware re-label: a 'stable' cat with high 1-mo MAPE is flagged
        if label == "stable" and not np.isnan(m1) and m1 > 18:
            label = "stable (watch)"
        stab.append(dict(category=c, stability_label=label, volatility_score=round(vol, 3),
                         mean_mape=round(m1, 2) if not np.isnan(m1) else None,
                         reason="config grouping + recent 1-mo MAPE"))
    stab_df = pd.DataFrame(stab)

    # next forecast (validated horizons) for Total_Cases + stable cats
    fc_rows = []
    for c in C.STABLE_CATEGORIES:
        if c not in series_map:
            continue
        nf = F.generate_next_forecast(series_map[c], category=c, horizons=C.HORIZONS)
        nf["category"] = c
        fc_rows.append(nf)
    next_fc = pd.concat(fc_rows, ignore_index=True) if fc_rows else pd.DataFrame()

    # ---- build leakage-free SAVED backtest forecasts (last up-to-6 months, 1-step) ----
    # These are real "previous forecast" records the Forecast-vs-Actual page can look up.
    backtest_rows = []          # (category, origin, target, forecast, actual, pct_err)
    for c in C.STABLE_CATEGORIES + C.HARD_CATEGORIES:
        if c not in series_map:
            continue
        s = series_map[c]
        n = len(s)
        for k in range(min(6, n - C.INITIAL_TRAIN_MONTHS - 1), 0, -1):
            ti = n - k
            if ti < C.INITIAL_TRAIN_MONTHS:
                continue
            train = s.values[:ti]
            origin = s.index[ti - 1]
            target = s.index[ti]
            fc = float(np.asarray(F.predict("Ensemble", train, 1, c, str(origin)))[0])
            actual = float(s.values[ti])
            pe = abs(actual - fc) / (abs(actual) + 1e-9) * 100
            backtest_rows.append(dict(category=c, origin=origin, target=target,
                                      forecast=fc, actual=actual, pct_err=pe))

    # persist run
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO model_runs(run_date,dataset_version,cutoff_date,run_type,models_used,horizons,status,runtime_seconds,notes)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (_now(), "latest", (max(series_map["Total_Cases"].index).strftime("%Y-%m-%d") if "Total_Cases" in series_map else ""),
                 run_type, ",".join(F.ALL_MODELS), ",".join(map(str, C.HORIZONS)),
                 "completed", round(time.time() - t0, 2),
                 f"{len(F.FALLBACK_LOG)} fallback events"))
    run_id = cur.lastrowid

    # 1) validation metrics (best model per cell)
    if not best.empty:
        for _, r in best.iterrows():
            cur.execute("""INSERT INTO validation_metrics(run_id,model_name,category,horizon,MAPE,sMAPE,MAE,RMSE,true_MASE,WAPE,practical_accuracy,sample_size,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (run_id, r["model"], r["category"], int(r["horizon"]), r.get("MAPE"),
                         r.get("sMAPE"), r.get("MAE"), r.get("RMSE"), r.get("true_MASE"),
                         r.get("WAPE"), r.get("practical_accuracy"), int(r.get("n_folds", 0)), _now()))

    # 2) saved future forecasts (validated horizons) — is_scenario_projection=0
    for _, r in next_fc.iterrows():
        cur.execute("""INSERT INTO forecasts(run_id,forecast_origin,target_date,horizon,
                       police_unit_or_national,category,model_name,forecast_value,is_scenario_projection,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, (max(series_map[r["category"]].index).strftime("%Y-%m-%d")
                              if r["category"] in series_map else ""),
                     r["target_date"], int(r["step"]), "national", r["category"],
                     r["model_name"], float(r["forecast_value"]), 0, _now()))

    # 3) saved backtest forecasts + 4) forecast-vs-actual comparisons
    for b in backtest_rows:
        cur.execute("""INSERT INTO forecasts(run_id,forecast_origin,target_date,horizon,
                       police_unit_or_national,category,model_name,forecast_value,is_scenario_projection,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, b["origin"].strftime("%Y-%m-%d"), b["target"].strftime("%Y-%m-%d"), 1,
                     "national", b["category"], "Ensemble", round(b["forecast"], 2), 0, _now()))
        fid = cur.lastrowid
        cur.execute("""INSERT INTO forecast_actual_comparisons(forecast_id,actual_date,actual_value,
                       forecast_value,error,absolute_error,percentage_error,smape_component,category,compared_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (fid, b["target"].strftime("%Y-%m-%d"), round(b["actual"], 2), round(b["forecast"], 2),
                     round(b["actual"] - b["forecast"], 2), round(abs(b["actual"] - b["forecast"]), 2),
                     round(b["pct_err"], 2), None, b["category"], _now()))

    # 5) drift per category (window-based: recent 3 months vs earlier window)
    drift_rows = []
    for c in C.STABLE_CATEGORIES + C.HARD_CATEGORIES:
        errs = [b["pct_err"] for b in backtest_rows if b["category"] == c]
        recent, baseline, pct, status, rec = D.window_drift(errs, recent_n=3)
        base_mape = best[(best.category == c) & (best.horizon == 1)]["MAPE"]
        base_mape = float(base_mape.iloc[0]) if len(base_mape) else None
        cur.execute("""INSERT INTO drift_monitoring(run_id,year,month,category,police_unit_or_national,
                       recent_mape,baseline_mape,percentage_error_change,drift_status,recommendation,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, None, None, c, "national",
                     (None if recent != recent else recent),
                     (None if baseline != baseline else baseline),
                     pct, status, rec, _now()))
        drift_rows.append(dict(category=c, recent_mape=recent, baseline_mape=baseline,
                               pct_change=pct, drift_status=status, recommendation=rec))
    drift_df = pd.DataFrame(drift_rows)

    # 6) category stability labels
    for _, r in stab_df.iterrows():
        cur.execute("""INSERT INTO category_stability_labels(category,stability_label,volatility_score,mean_mape,reason,updated_at)
                       VALUES(?,?,?,?,?,?)""",
                    (r["category"], r["stability_label"], r.get("volatility_score"),
                     r.get("mean_mape"), r.get("reason"), _now()))

    # 7) persist model fallback events (memory-loss proof: written to the DB, shown in Audit Log)
    for fb in F.FALLBACK_LOG:
        cur.execute("INSERT INTO model_fallback_log(run_id,model_name,category,horizon,forecast_origin,error_message,fallback_model,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (run_id, fb.get("model_name"), str(fb.get("category")), int(fb.get("horizon") or 0),
                     str(fb.get("forecast_origin")), str(fb.get("error_message"))[:300],
                     fb.get("fallback_model", "SeasonalNaive"), _now()))
    # 8) record the recalibration run itself in the human-readable audit log
    cur.execute("INSERT INTO audit_logs(table_name,record_id,action,new_value,changed_by,changed_at,reason) VALUES(?,?,?,?,?,?,?)",
                ("model_runs", str(run_id), "RECALIBRATION",
                 f"{len(F.FALLBACK_LOG)} model fallback(s) logged", created_by, _now(),
                 "recalibration completed; forecasts/metrics/drift persisted"))

    conn.commit(); conn.close()

    overall_drift = ("critical" if (drift_df["drift_status"] == "critical").any()
                     else "warning" if (drift_df["drift_status"] == "warning").any()
                     else "normal" if len(drift_df) and (drift_df["drift_status"] == "normal").any()
                     else "unknown")
    return dict(run_id=run_id, cv=cv, best=best, stability=stab_df, next_forecast=next_fc,
                drift=drift_df, overall_drift=overall_drift,
                fallback_log=F.fallback_log_df(), runtime=round(time.time() - t0, 2),
                series_map=series_map)

"""FAST_SAFE forecasting: Naive, Seasonal Naive, ETS, Theta, ARIMA, SARIMA, LightGBM, Ensemble.
Leakage-free rolling-origin. Explicit fallback logging (no silent failures). No Transformer.
"""
from __future__ import annotations
import warnings
import hashlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeout
import numpy as np
import pandas as pd
import config as C
from . import metrics as M

warnings.filterwarnings("ignore")
M_SEAS = C.SEASONAL_PERIOD
RS = C.RANDOM_SEED

FALLBACK_LOG: list[dict] = []

# Per-process bounded LRU cache of forecasts within (and across) recalibration runs.
# Bounded to avoid memory growth on a long-running Streamlit server.
_FORECAST_CACHE: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_FORECAST_CACHE_MAX = 2048

# Per-model wall-clock budget (seconds). Risky statsmodels fits on hard/noisy short series
# can occasionally stall; we cap them and fall back to seasonal naive (logged). This does not
# change methodology — it only prevents hangs and is recorded in the auditable fallback log.
_MODEL_TIMEOUT_S = getattr(C, "MODEL_TIMEOUT_SECONDS", 20)

# A small private executor lets us cap each risky fit with concurrent.futures.
# Works on any platform and any thread (unlike signal.SIGALRM), which is essential under
# Streamlit's worker-thread model.
_TIMEOUT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="phq-fit")


class _Timeout(Exception):
    pass


def _with_timeout(fn, seconds):
    """Cross-platform wall-clock timeout: submits fn to a thread pool and raises _Timeout
    if it doesn't finish within `seconds`. Safe under Streamlit (worker threads) and Windows."""
    fut = _TIMEOUT_EXECUTOR.submit(fn)
    try:
        return fut.result(timeout=seconds)
    except _FTimeout:
        # We can't preempt CPython threads cleanly; the rogue thread will exit on its own.
        # The fallback path returns immediately and is recorded in the fallback log.
        fut.cancel()
        raise _Timeout(f"fit exceeded {seconds}s")


def clear_cache():
    _FORECAST_CACHE.clear()


def _cache_get(key):
    v = _FORECAST_CACHE.get(key)
    if v is not None:
        _FORECAST_CACHE.move_to_end(key)
    return v


def _cache_put(key, value):
    _FORECAST_CACHE[key] = value
    _FORECAST_CACHE.move_to_end(key)
    while len(_FORECAST_CACHE) > _FORECAST_CACHE_MAX:
        _FORECAST_CACHE.popitem(last=False)


def _log(model, category, horizon, origin, err, fallback="SNaive"):
    FALLBACK_LOG.append(dict(model_name=model, category=str(category), horizon=int(horizon),
                             forecast_origin=str(origin), error_message=str(err)[:300],
                             fallback_model=fallback))


def fallback_log_df():
    cols = ["model_name", "category", "horizon", "forecast_origin", "error_message", "fallback_model"]
    return pd.DataFrame(FALLBACK_LOG, columns=cols)


# ---------------- individual models ----------------
def fit_naive(train, h):
    return np.repeat(float(train[-1]), h)


def fit_seasonal_naive(train, h):
    n = len(train)
    if n >= M_SEAS:
        base = train[-M_SEAS:]
        return np.array([base[i % M_SEAS] for i in range(h)], float)
    return np.repeat(float(train[-1]), h)


def fit_ets(train, h):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    seas = "add" if len(train) >= 2 * M_SEAS else None
    mod = ExponentialSmoothing(train, trend="add", seasonal=seas,
                               seasonal_periods=M_SEAS if seas else None,
                               initialization_method="estimated").fit()
    return np.asarray(mod.forecast(h), float)


def fit_theta(train, h):
    from statsmodels.tsa.forecasting.theta import ThetaModel
    return np.asarray(ThetaModel(pd.Series(train), period=M_SEAS).fit().forecast(h), float)


def fit_arima(train, h):
    from statsmodels.tsa.arima.model import ARIMA
    return np.asarray(ARIMA(train, order=(1, 1, 1)).fit().forecast(h), float)


def fit_sarima(train, h):
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    mod = SARIMAX(train, order=(1, 1, 1), seasonal_order=(0, 1, 1, M_SEAS),
                  enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
    return np.asarray(mod.forecast(h), float)


def fit_lightgbm(train, h, n_lags=12):
    import lightgbm as lgb
    yl = np.log1p(np.clip(train, 0, None)); n = len(yl)
    if n <= n_lags + 6:
        raise RuntimeError("insufficient history for LightGBM lags")
    X = [yl[i - n_lags:i] for i in range(n_lags, n)]
    t = [yl[i] for i in range(n_lags, n)]
    mdl = lgb.LGBMRegressor(objective="regression", n_estimators=200, learning_rate=0.05,
                            num_leaves=15, min_child_samples=5, subsample=0.9,
                            colsample_bytree=0.9, random_state=RS, verbosity=-1,
                            n_jobs=1, force_col_wise=True).fit(np.array(X), np.array(t))
    hist = list(yl); out = []
    for _ in range(h):
        p = mdl.predict(np.array(hist[-n_lags:]).reshape(1, -1))[0]
        out.append(p); hist.append(p)
    return np.expm1(np.array(out))


RISKY = {"ETS": fit_ets, "Theta": fit_theta, "ARIMA": fit_arima,
         "SARIMA": fit_sarima, "LightGBM": fit_lightgbm}
TRIVIAL = {"Naive": fit_naive, "SeasonalNaive": fit_seasonal_naive}
ALL_MODELS = ["Naive", "SeasonalNaive", "ETS", "Theta", "ARIMA", "SARIMA", "LightGBM", "Ensemble"]


def forecast_one(model, train, h, category="?", origin="?"):
    train = np.asarray(train, float)
    if model in TRIVIAL:
        return TRIVIAL[model](train, h)
    # cache identical (model, train, horizon) within a run to avoid refits
    key = (model, int(h), hashlib.md5(train.tobytes()).hexdigest())
    cached = _cache_get(key)
    if cached is not None:
        return cached
    hi = 5.0 * np.nanmax(train) if len(train) else np.inf   # plausible upper bound (matches notebook guard)
    try:
        out = np.asarray(_with_timeout(lambda: RISKY[model](train, h), _MODEL_TIMEOUT_S), float)
        if (out.shape[0] < h or not np.all(np.isfinite(out))
                or np.any(out < 0) or np.any(out > hi)):
            raise RuntimeError("non-finite/out-of-range -> SNaive")
        res = out[:h]
    except _Timeout:
        _log(model, category, h, origin, f"timeout>{_MODEL_TIMEOUT_S}s")
        res = fit_seasonal_naive(train, h)
    except Exception as e:
        _log(model, category, h, origin, e)
        res = fit_seasonal_naive(train, h)
    _cache_put(key, res)
    return res


def fast_safe_ensemble(train, h, category="?", origin="?"):
    if getattr(C, "FAST_DEMO_MODE", False):
        members = getattr(C, "DEMO_ENSEMBLE_MEMBERS", ["SeasonalNaive", "Theta", "LightGBM"])
    else:
        members = ["ETS", "Theta", "ARIMA", "SARIMA", "LightGBM"]
    preds = [forecast_one(m, train, h, category, origin) for m in members]
    return np.clip(np.mean(preds, axis=0), 0, None)


def predict(model, train, h, category="?", origin="?"):
    if model == "Ensemble":
        return fast_safe_ensemble(train, h, category, origin)
    return forecast_one(model, train, h, category, origin)


# ---------------- rolling-origin validation ----------------
def rolling_origin(series: pd.Series, category="?", models=None,
                   horizons=None, initial=None, step=None, max_folds=None):
    models = models or ALL_MODELS
    horizons = horizons or C.HORIZONS
    initial = initial or C.INITIAL_TRAIN_MONTHS
    step = step or C.CV_STEP
    max_folds = max_folds or C.MAX_FOLDS
    y = series.astype(float).values
    idx = series.index
    n = len(y)
    rows = []
    for h in horizons:
        origins, o = [], initial
        while o + h <= n and len(origins) < max_folds:
            origins.append(o); o += step
        if not origins:
            continue
        for model in models:
            errs = []
            for org in origins:
                tr, te = y[:org], y[org:org + h]
                fc = predict(model, tr, h, category, str(idx[org]))
                errs.append(M.all_metrics(te, np.asarray(fc)[:h], tr))
            agg = {k: float(np.nanmean([e[k] for e in errs])) for k in errs[0]}
            rows.append(dict(category=category, horizon=h, model=model, n_folds=len(origins), **agg))
    return pd.DataFrame(rows)


def best_model_per_cell(cv_df: pd.DataFrame) -> pd.DataFrame:
    """FAST_SAFE selection: best model per (category, horizon) by MAPE."""
    if cv_df.empty:
        return cv_df
    idx = cv_df.groupby(["category", "horizon"])["MAPE"].idxmin()
    best = cv_df.loc[idx].copy()
    best["practical_accuracy"] = (100 - best["MAPE"]).round(2)
    return best


def generate_next_forecast(series: pd.Series, category="?", horizons=None, scenario_to=None):
    """Forecast next `horizons` months from the end of the series using the ensemble.
    If scenario_to (Timestamp) given, extend monthly to that date as a SCENARIO."""
    horizons = horizons or C.HORIZONS
    last = series.index.max()
    out = []
    hmax = max(horizons)
    if scenario_to is not None:
        hmax = max(hmax, (scenario_to.to_period("M") - last.to_period("M")).n)
    fc = fast_safe_ensemble(series.values, hmax, category, str(last))
    fdates = pd.date_range(last + pd.offsets.MonthBegin(1), periods=hmax, freq="MS")
    for i, (d, v) in enumerate(zip(fdates, fc), start=1):
        out.append(dict(target_date=d.strftime("%Y-%m-%d"), step=i, model_name="Ensemble",
                        forecast_value=round(float(v), 1),
                        is_scenario_projection=int(scenario_to is not None and d > (last + pd.offsets.MonthBegin(max(horizons))))))
    return pd.DataFrame(out)

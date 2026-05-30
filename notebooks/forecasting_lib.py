"""
Forecasting library for Bangladesh PHQ reported-crime data.
Modular FAST_SAFE forecasting functions (Naive, SNaive, ETS, Theta, ARIMA, SARIMA, LightGBM, Ensemble).
Designed for transparent, auditable reading: every function is short, fallback-explicit, no hidden state.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

RS = 42
SEASONAL_PERIOD = 12


def f_naive(y: np.ndarray, h: int) -> np.ndarray:
    """Naive forecast: last observation repeated h times. No-skill baseline."""
    return np.repeat(y[-1], h)


def f_snaive(y: np.ndarray, h: int, m: int = SEASONAL_PERIOD) -> np.ndarray:
    """Seasonal Naive: last full seasonal cycle repeated. Strong baseline for monthly data."""
    if len(y) >= m:
        base = y[-m:]
        return np.array([base[i % m] for i in range(h)])
    return np.repeat(y[-1], h)


def f_ets(y: np.ndarray, h: int, m: int = SEASONAL_PERIOD) -> np.ndarray:
    """ETS (Holt-Winters additive). Falls back to SNaive on convergence failure."""
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        seas = "add" if len(y) >= 2 * m else None
        mod = ExponentialSmoothing(y, trend="add", seasonal=seas,
                                   seasonal_periods=m if seas else None,
                                   initialization_method="estimated").fit()
        return np.asarray(mod.forecast(h))
    except Exception:
        return f_snaive(y, h, m)


def f_theta(y: np.ndarray, h: int, m: int = SEASONAL_PERIOD) -> np.ndarray:
    """Theta model. Falls back to SNaive on failure."""
    try:
        from statsmodels.tsa.forecasting.theta import ThetaModel
        mod = ThetaModel(pd.Series(y), period=m).fit()
        return np.asarray(mod.forecast(h))
    except Exception:
        return f_snaive(y, h, m)


def f_arima(y: np.ndarray, h: int, m: int = SEASONAL_PERIOD) -> np.ndarray:
    """ARIMA(1,1,1). Falls back to SNaive on failure."""
    try:
        from statsmodels.tsa.arima.model import ARIMA
        mod = ARIMA(y, order=(1, 1, 1)).fit()
        return np.asarray(mod.forecast(h))
    except Exception:
        return f_snaive(y, h, m)


def f_sarima(y: np.ndarray, h: int, m: int = SEASONAL_PERIOD) -> np.ndarray:
    """SARIMA(1,1,1)(0,1,1,12). Falls back to SNaive on failure."""
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        mod = SARIMAX(y, order=(1, 1, 1), seasonal_order=(0, 1, 1, m),
                      enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
        return np.asarray(mod.forecast(h))
    except Exception:
        return f_snaive(y, h, m)


def f_lgbm(y: np.ndarray, h: int, n_lags: int = 12) -> np.ndarray:
    """LightGBM recursive forecast on log1p-stabilized lag features.
    Falls back to SNaive if insufficient history. No future leakage."""
    import lightgbm as lgb
    yl = np.log1p(np.clip(y, 0, None))
    n = len(yl)
    if n <= n_lags + 6:
        return f_snaive(y, h)
    X, t = [], []
    for i in range(n_lags, n):
        X.append(yl[i - n_lags:i])
        t.append(yl[i])
    X = np.array(X); t = np.array(t)
    params = dict(objective="regression", n_estimators=200, learning_rate=0.05,
                  num_leaves=15, min_child_samples=5, subsample=0.9,
                  colsample_bytree=0.9, random_state=RS, verbosity=-1)
    mdl = lgb.LGBMRegressor(**params).fit(X, t)
    hist = list(yl)
    out = []
    for _ in range(h):
        feat = np.array(hist[-n_lags:]).reshape(1, -1)
        p = mdl.predict(feat)[0]
        out.append(p); hist.append(p)
    return np.expm1(np.array(out))


MODELS = ["Naive", "SNaive", "ETS", "Theta", "ARIMA", "SARIMA", "LGBM"]
ALL_MODELS = MODELS + ["Ensemble"]
M = SEASONAL_PERIOD  # alias for notebook compatibility


def forecast_one(y: np.ndarray, h: int, model: str) -> np.ndarray:
    """Single-model forecast dispatcher. Returns h-step prediction array.

    A sanity guard rejects non-finite or numerically-absurd outputs (e.g. SARIMAX can
    occasionally diverge on series with a large structural break such as the 2020 COVID dip)
    and falls back to the seasonal-naive forecast. Every fallback is appended to FALLBACK_LOG
    for auditability. This is a robustness guard only; it does not change model methodology."""
    fn_map = {"Naive": f_naive, "SNaive": f_snaive, "ETS": f_ets, "Theta": f_theta,
              "ARIMA": f_arima, "SARIMA": f_sarima, "LGBM": f_lgbm}
    if model not in fn_map:
        raise ValueError(f"Unknown model: {model}")
    y = np.asarray(y, float)
    out = np.asarray(fn_map[model](y, h), float)
    hi = 5.0 * np.nanmax(y) if len(y) else np.inf   # plausible upper bound
    bad = (out.shape[0] < h) or (not np.all(np.isfinite(out))) or np.any(out < 0) or np.any(out > hi)
    if bad:
        FALLBACK_LOG.append(dict(category="?", model=model, horizon=h, fold="-",
                                 reason="non-finite/out-of-range -> SNaive"))
        return f_snaive(y, h)
    return out[:h]


def ensemble(y: np.ndarray, h: int) -> np.ndarray:
    """Ensemble forecast: mean of ETS, Theta, ARIMA, SARIMA, LGBM. Each member passes through
    the forecast_one sanity guard, so a single diverging member cannot poison the average."""
    preds = [forecast_one(y, h, m) for m in ["ETS", "Theta", "ARIMA", "SARIMA", "LGBM"]]
    return np.mean(preds, axis=0)


def metrics(actual, pred, train_for_mase=None, m: int = SEASONAL_PERIOD) -> dict:
    """Forecasting error metrics: MAPE, WAPE, sMAPE, MAE, RMSE, true_MASE (seasonal scale).
    Leakage-free: uses only training data for MASE denominator (seasonal Naive baseline)."""
    a = np.asarray(actual, float); p = np.asarray(pred, float)
    eps = 1e-9
    nz = np.abs(a) > eps
    mape = np.mean(np.abs((a[nz] - p[nz]) / a[nz])) * 100 if nz.any() else np.nan
    wape = np.sum(np.abs(a - p)) / (np.sum(np.abs(a)) + eps) * 100
    smape = np.mean(2 * np.abs(a - p) / (np.abs(a) + np.abs(p) + eps)) * 100
    mae = np.mean(np.abs(a - p))
    rmse = np.sqrt(np.mean((a - p) ** 2))
    mase = np.nan
    if train_for_mase is not None and len(train_for_mase) > m:
        tr = np.asarray(train_for_mase, float)
        d = np.mean(np.abs(tr[m:] - tr[:-m]))
        if d > eps:
            mase = mae / d
    return dict(MAPE=mape, WAPE=wape, sMAPE=smape, MAE=mae, RMSE=rmse, true_MASE=mase)


# Public fallback log: every risky model fit that fails is appended here for auditability.
FALLBACK_LOG: list = []


def fallback_log_df() -> pd.DataFrame:
    """Return current fallback log as a DataFrame for audit/display."""
    if not FALLBACK_LOG:
        return pd.DataFrame(columns=["category", "model", "horizon", "fold", "reason"])
    return pd.DataFrame(FALLBACK_LOG)


def rolling_origin(series, horizons=(1, 3, 6, 12), category: str = None,
                   initial_train: int = 36, step: int = 6, max_folds: int = 5) -> pd.DataFrame:
    """Leakage-free rolling-origin CV. Expanding window: train on [0:origin], test on [origin:origin+h].
    Origin advances by `step` each fold. Returns DataFrame of per-(model, horizon, fold) metrics.
    Optional `category` label is appended to each row for downstream grouping."""
    y = np.asarray(series.values if hasattr(series, "values") else series, float)
    n = len(y)
    rows = []
    for h in horizons:
        origins = []
        o = initial_train
        while o + h <= n and len(origins) < max_folds:
            origins.append(o); o += step
        if not origins:
            continue
        for model in ALL_MODELS:
            for fold_i, org in enumerate(origins):
                train = y[:org]
                test = y[org:org + h]
                try:
                    if model == "Ensemble":
                        fc = ensemble(train, h)
                    else:
                        fc = forecast_one(train, h, model)
                except Exception as e:
                    FALLBACK_LOG.append(dict(category=category, model=model, horizon=h,
                                             fold=fold_i, reason=str(e)[:120]))
                    fc = f_snaive(train, h)
                fc = np.asarray(fc[:h], float)
                mk = metrics(test, fc, train)
                rows.append(dict(category=category, model=model, horizon=h, fold=fold_i, **mk))
    return pd.DataFrame(rows)

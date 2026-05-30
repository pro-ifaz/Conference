"""Forecast error metrics: MAPE, sMAPE, MAE, RMSE, true_MASE (seasonal), WAPE."""
import numpy as np
import config as C

M_SEAS = C.SEASONAL_PERIOD


def all_metrics(actual, pred, train_for_mase=None):
    a = np.asarray(actual, float); p = np.asarray(pred, float); eps = 1e-9
    nz = np.abs(a) > eps
    mape = float(np.mean(np.abs((a[nz] - p[nz]) / a[nz])) * 100) if nz.any() else np.nan
    smape = float(np.mean(2 * np.abs(a - p) / (np.abs(a) + np.abs(p) + eps)) * 100)
    mae = float(np.mean(np.abs(a - p)))
    rmse = float(np.sqrt(np.mean((a - p) ** 2)))
    wape = float(np.sum(np.abs(a - p)) / (np.sum(np.abs(a)) + eps) * 100)
    mase = np.nan
    if train_for_mase is not None and len(train_for_mase) > M_SEAS:
        tr = np.asarray(train_for_mase, float)
        d = float(np.mean(np.abs(tr[M_SEAS:] - tr[:-M_SEAS])))
        if d > eps:
            mase = mae / d
    return dict(MAPE=mape, sMAPE=smape, MAE=mae, RMSE=rmse, true_MASE=mase, WAPE=wape)


def practical_accuracy(mape):
    return None if mape is None or np.isnan(mape) else round(100 - mape, 2)

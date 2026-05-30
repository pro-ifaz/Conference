import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
import config as C
from modules import db, recalibration as R
from utils import ui

st.set_page_config(page_title="Model Metrics", page_icon="📐", layout="wide")
user = ui.require_login(); ui.header("Model error metrics (rolling-origin)")
ui.practical_note()

if ui.can(user, "recalibrate") and st.button("Run recalibration now"):
    with st.spinner("Computing rolling-origin metrics… (fast demo mode)"):
        res = R.recalibrate(created_by=user["username"])
        st.session_state["last_run"] = res
        st.session_state["last_drift_status"] = res.get("overall_drift", "unknown")
    st.success(f"Run #{res['run_id']} done in {res['runtime']}s ({len(res['fallback_log'])} fallbacks).")

# DB-backed: read latest persisted metrics (survives restart)
vm = db.latest_validation_metrics()
if vm.empty:
    st.info("No saved model metrics found. Please run recalibration first.")
    st.stop()

st.markdown("#### Best model per category × horizon (FAST_SAFE selection) — from database")
st.dataframe(vm[["category", "horizon", "model_name", "MAPE", "practical_accuracy",
                 "true_MASE", "sMAPE", "MAE", "RMSE", "WAPE"]].round(2),
             use_container_width=True, height=380)

st.markdown("#### Horizon-wise stable mean")
hz = (vm[vm.category.isin(C.STABLE_CATEGORIES)]
      .groupby("horizon")[["MAPE", "practical_accuracy", "true_MASE"]].mean().round(2))
st.dataframe(hz, use_container_width=True, hide_index=True)
st.caption("LIVE rolling-origin results (regenerated, persisted in SQLite). The archived thesis "
           "verification (92.5% Total_Cases) is kept separate and not mixed here.")

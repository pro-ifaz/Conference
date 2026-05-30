import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from modules import audit
from modules.db import get_conn
from utils import ui
st.set_page_config(page_title="Audit Log", page_icon="🗂️", layout="wide")
user = ui.require_login(); ui.header("Audit log")

df = audit.fetch(1000)
if df.empty:
    st.info("No audit entries yet. Add or approve monthly data, or run a recalibration, to populate the log.")
else:
    c = st.columns(3)
    act = c[0].multiselect("Action", sorted(df.action.dropna().unique()))
    usr = c[1].multiselect("User", sorted(df.changed_by.dropna().unique()))
    custom_only = c[2].checkbox("Custom field changes only")
    f = df.copy()
    if act: f = f[f.action.isin(act)]
    if usr: f = f[f.changed_by.isin(usr)]
    if custom_only: f = f[f.custom_field_flag == 1]
    st.dataframe(f[["changed_at","action","changed_by","affected_year","affected_month","affected_unit",
                    "affected_category","reason","old_value","new_value","custom_field_flag"]],
                 use_container_width=True, height=420)

# --- Persistent model fallback log (written by every recalibration run) ---
st.divider()
st.markdown("#### Model fallback log (persisted)")
st.caption("Whenever a model produces a non-finite, negative, or implausibly large value, the system "
           "falls back to Seasonal Naive and records it here. It is written to the database, so it "
           "survives restarts. An empty table means every model fit produced a valid forecast.")
conn = get_conn()
try:
    fb = pd.read_sql_query(
        "SELECT created_at, run_id, model_name, category, horizon, forecast_origin, "
        "fallback_model, error_message FROM model_fallback_log ORDER BY fallback_id DESC LIMIT 500", conn)
except Exception:
    fb = pd.DataFrame()
conn.close()
if fb.empty:
    st.success("No model fallback events recorded; all model fits produced valid forecasts.")
else:
    st.metric("Recorded fallback events", len(fb))
    st.dataframe(fb, use_container_width=True, hide_index=True, height=300)

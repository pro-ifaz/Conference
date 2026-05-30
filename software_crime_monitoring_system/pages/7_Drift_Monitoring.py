import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
import config as C
from modules import db, recalibration as R
from utils import ui

st.set_page_config(page_title="Drift Monitoring", page_icon="📡", layout="wide")
user = ui.require_login(); ui.header("Drift monitoring")
st.caption("Recent-vs-baseline drift on saved forecast-vs-actual errors: baseline = earlier window mean "
           "abs% error, recent = last 3 months mean. Connected to the loop: new actual → error → drift "
           "check → recalibration decision → next forecast.")
st.markdown(f"""<div class="note"><b>Thresholds (explainable):</b> normal &lt; +20% error increase ·
warning +20–50% (or strong deviation) · critical &gt; +50%. Recommendations: keep model · recalibrate ·
review source data · mark category as noisy.</div>""", unsafe_allow_html=True)

# read the latest persisted drift rows
conn = db.get_conn()
last_run = pd.read_sql_query("SELECT MAX(run_id) r FROM drift_monitoring", conn).iloc[0]["r"]
df = pd.DataFrame()
if last_run is not None:
    df = pd.read_sql_query(
        """SELECT category, recent_mape, baseline_mape, percentage_error_change AS pct_change,
                  drift_status, recommendation, created_at
           FROM drift_monitoring WHERE run_id=? ORDER BY category""", conn, params=[int(last_run)])
conn.close()

if df.empty:
    st.info("No drift results stored yet.")
    if ui.can(user, "recalibrate") and st.button("Run recalibration now (computes & stores drift)"):
        with st.spinner("Recalibrating + computing drift…"):
            res = R.recalibrate(created_by=user["username"])
        st.session_state["last_run"] = res
        st.session_state["last_drift_status"] = res["overall_drift"]
        st.rerun()
    st.stop()

overall = ("critical" if (df.drift_status == "critical").any()
           else "warning" if (df.drift_status == "warning").any()
           else "normal" if (df.drift_status == "normal").any() else "unknown")
st.session_state["last_drift_status"] = overall
st.markdown(f"#### Overall drift status (run #{int(last_run)}): " + ui.drift_badge(overall),
            unsafe_allow_html=True)

def color(v):
    return {"normal": "background-color:#dcfce7", "warning": "background-color:#fef9c3",
            "critical": "background-color:#fee2e2", "unknown": "background-color:#f3f4f6"}.get(v, "")
st.dataframe(df.style.map(color, subset=["drift_status"]), use_container_width=True, height=420, hide_index=True)
st.caption("A stable category whose recent error rises into warning/critical is a signal to recalibrate "
           "or review the source data; persistently noisy categories can be marked noisy.")

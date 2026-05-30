import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
import config as C
from modules import db, recalibration as R
from utils import ui

st.set_page_config(page_title="Category Stability", page_icon="🧩", layout="wide")
user = ui.require_login(); ui.header("Category stability (stable vs hard/noisy)")
run = st.session_state.get("last_run")
if not run and ui.can(user, "recalibrate") and st.button("Run recalibration now"):
    run = R.recalibrate(created_by=user["username"]); st.session_state["last_run"] = run

# prefer persisted labels; fall back to session run
conn = db.get_conn()
last = pd.read_sql_query("SELECT MAX(label_id) m FROM category_stability_labels", conn).iloc[0]["m"]
stab = pd.DataFrame()
if last is not None:
    stab = pd.read_sql_query(
        """SELECT category, stability_label, volatility_score, mean_mape, reason, updated_at
           FROM category_stability_labels
           WHERE updated_at=(SELECT MAX(updated_at) FROM category_stability_labels)""", conn)
drift = pd.read_sql_query("SELECT category, drift_status, recommendation FROM drift_monitoring "
                          "WHERE run_id=(SELECT MAX(run_id) FROM drift_monitoring)", conn)
conn.close()

if stab.empty and run is not None:
    stab = run["stability"]
if stab.empty:
    st.info("No stability labels yet. Recalibrate from Add Monthly Data or Model Metrics."); st.stop()

if not drift.empty:
    stab = stab.merge(drift, on="category", how="left")  # add drift impact

st.dataframe(stab, use_container_width=True, height=380, hide_index=True)
st.caption("Stable categories form the headline average; hard/noisy categories are reported but kept out "
           "of headline claims. Labels update only from approved active data. The drift_status column "
           "shows whether recent performance suggests degradation (warning/critical → review/recalibrate).")

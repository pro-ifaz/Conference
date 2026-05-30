import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import config as C
from modules import db
from utils import ui

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
user = ui.require_login(); ui.header("Operational dashboard")

months = db.months_present()
nat = db.national_series("Total_Cases", approved_only=True)
run = db.latest_run()                 # DB-backed (survives restart)
drift = db.latest_drift_status()
fc_n = db.forecast_count()

c = st.columns(4)
ui.kpi(c[0], "Coverage", f"{len(nat)} months",
       f"{nat.index.min():%Y-%m} – {nat.index.max():%Y-%m}" if len(nat) else "—")
ui.kpi(c[1], "Reporting units", f"{db.list_units().shape[0]}", "active standard + custom")
ui.kpi(c[2], "Latest approved month", f"{nat.index.max():%Y-%m}" if len(nat) else "—",
       f"Total Cases {int(nat.iloc[-1]):,}" if len(nat) else "no data")
pending = months[months.verification_status != "approved"]
ui.kpi(c[3], "Pending / draft months", f"{pending.shape[0]}", "awaiting approval")

st.markdown("#### National monthly Total Cases (reported)")
if len(nat):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=nat.index, y=nat.values, mode="lines", name="Total Cases",
                             line=dict(color="#2563eb")))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="Total Cases", template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No approved data yet. Add a month from **Add Monthly Data**.")

cc = st.columns(3)
with cc[0]:
    st.markdown("#### Latest model run")
    if run:
        st.write(f"Run #{int(run['run_id'])} · {run.get('run_type','')} · {run.get('runtime_seconds','?')}s")
        st.caption(f"{run.get('run_date','')} — {run.get('notes','')}")
    else:
        st.caption("No run yet. Run recalibration (Add Monthly Data → Approve, or Model Metrics).")
with cc[1]:
    st.markdown("#### Saved forecasts")
    ui.kpi(st.container(), "Forecast rows stored", f"{fc_n:,}", "in SQLite")
with cc[2]:
    st.markdown("#### Drift status")
    st.markdown(ui.drift_badge(drift or "unknown"), unsafe_allow_html=True)
    st.caption("See **Drift Monitoring** for detail.")

vm = db.latest_validation_metrics()
if not vm.empty:
    st.markdown("#### Latest validation metrics (best model per category × horizon)")
    st.dataframe(vm[["category", "horizon", "model_name", "MAPE", "practical_accuracy", "true_MASE"]]
                 .round(2), use_container_width=True, height=240)

st.divider()
st.caption("Archived thesis verification (separate from this live system): the May-2025 cutoff forecast "
           "verified at 92.5% practical accuracy for national Total Cases vs actual PHQ data "
           "(Jun 2025–Apr 2026). Live recalculations may differ slightly and are labelled as such. "
           "Future forecasts are scenario projections only.")

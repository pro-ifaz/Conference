"""Scenario projection page: future months marked clearly as not validated.

This page is time-independent. The horizon and the projection cap are taken RELATIVE to the
latest observed month in the data, never a fixed calendar year, so the tool behaves the same
whatever PHQ dataset (and whatever final month) is loaded.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import config as C
from modules import db, forecasting as F, export_reports as EX
from utils import ui

st.set_page_config(page_title="Scenario Projection", page_icon="🔮", layout="wide")
user = ui.require_login(); ui.header("Future scenario projection")
ui.scenario_warning()
cat = st.selectbox("Category", C.STABLE_CATEGORIES)
s = db.national_series(cat, approved_only=True)
if len(s) < 24:
    st.info("Not enough history."); st.stop()

last_obs = s.index.max()
# Hard cap on how far the user can project. RELATIVE to the latest observation (not a fixed year),
# so the page is time-independent. MAX_SCENARIO_HORIZON_MONTHS is set in config.py.
max_dt = (last_obs + pd.offsets.MonthBegin(C.MAX_SCENARIO_HORIZON_MONTHS))
min_dt = (last_obs + pd.offsets.MonthBegin(1))

st.markdown("**How many months ahead do you want to forecast?**")
hsel = st.radio("Forecast horizon", [1, 3, 6, 12, "Custom date"], index=3, horizontal=True,
                help="The validated horizons are 1, 3, 6, and 12 months. Anything past the last "
                     "observed month is a planning scenario, not a verified prediction.")
if hsel == "Custom date":
    default_dt = min(last_obs + pd.offsets.MonthBegin(12), max_dt)
    to = st.date_input("Project to (month)", default_dt, min_value=min_dt, max_value=max_dt)
    to = pd.Timestamp(to).to_period("M").to_timestamp()
else:
    to = (last_obs + pd.offsets.MonthBegin(int(hsel))).to_period("M").to_timestamp()
to = min(to, max_dt)
if to < min_dt:
    st.warning(f"Projection target must be after {min_dt:%Y-%m}.")
    st.stop()
months_ahead = (to.to_period("M") - last_obs.to_period("M")).n
st.caption(f"Forecasting from {last_obs:%Y-%m} to {to:%Y-%m} ({months_ahead} month(s) ahead). "
           f"Latest observed month in the loaded data: {last_obs:%Y-%m}.")

nf = F.generate_next_forecast(s, category=cat, horizons=C.HORIZONS, scenario_to=to)
nf["label"] = "SCENARIO PROJECTION ONLY (not verified accuracy)"
fig = go.Figure()
fig.add_trace(go.Scatter(x=s.index, y=s.values, name="observed (approved)", line=dict(color="#111827")))
fd = pd.to_datetime(nf["target_date"])
fig.add_trace(go.Scatter(x=fd, y=nf["forecast_value"], name="scenario projection",
                         line=dict(color="#e76f51", dash="dash")))
fig.add_vline(x=s.index.max(), line_dash="dot", line_color="gray")
fig.update_layout(height=380, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, use_container_width=True)
st.dataframe(nf, use_container_width=True, height=300, hide_index=True)
st.download_button("⬇️ Export scenario (CSV)", EX.to_csv_bytes(nf),
                   file_name=f"scenario_{cat}.csv", mime="text/csv")

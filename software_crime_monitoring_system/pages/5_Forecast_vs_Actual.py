import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
import plotly.graph_objects as go
import streamlit as st
import config as C
from modules import db, forecasting as F
from utils import ui

st.set_page_config(page_title="Forecast vs Actual", page_icon="🎯", layout="wide")
user = ui.require_login(); ui.header("Forecast vs actual (uses SAVED previous forecasts)")
st.caption("Per the methodology, this compares a PREVIOUSLY SAVED forecast for the target month against "
           "the newly approved actual PHQ data. Saved forecasts are created by recalibration "
           "(Add Monthly Data → Approve & recalibrate, or Model Metrics → Run recalibration).")

cat = st.selectbox("Category", C.STABLE_CATEGORIES + C.HARD_CATEGORIES)

# pull saved (non-scenario) forecasts for this category from the forecasts table
conn = db.get_conn()
saved = pd.read_sql_query(
    """SELECT run_id, forecast_origin, target_date, horizon, model_name, forecast_value, created_at
       FROM forecasts
       WHERE category=? AND police_unit_or_national='national' AND is_scenario_projection=0
       ORDER BY target_date""", conn, params=[cat])
conn.close()

s = db.national_series(cat, approved_only=True)  # active approved actuals only

if saved.empty:
    st.warning("No previous saved forecast found. Run a recalibration first to create saved forecast "
               "rows (Add Monthly Data → Approve & recalibrate, or Model Metrics → Run recalibration).")
else:
    saved["target_date"] = pd.to_datetime(saved["target_date"])
    # only target months that we now have an approved actual for
    have_actual = saved[saved["target_date"].isin(s.index)].copy()
    if have_actual.empty:
        st.warning("No previous saved forecast found for a month that also has approved actual data yet. "
                   "Saved forecasts exist for future months; comparison will appear once their actuals are added.")
    else:
        target = st.selectbox("Target month (with a saved forecast and an approved actual)",
                              sorted(have_actual["target_date"].dt.strftime("%Y-%m").unique()),
                              index=len(have_actual["target_date"].unique()) - 1)
        row = have_actual[have_actual["target_date"].dt.strftime("%Y-%m") == target].iloc[-1]
        fc = float(row["forecast_value"]); actual = float(s.loc[pd.Timestamp(target + "-01")])
        err = actual - fc; pe = abs(err) / (abs(actual) + 1e-9) * 100
        st.success(f"Using SAVED forecast from run #{int(row['run_id'])} "
                   f"(origin {row['forecast_origin']}, model {row['model_name']}, horizon {int(row['horizon'])}).")
        c = st.columns(3)
        ui.kpi(c[0], "Saved forecast", f"{fc:,.0f}", f"made at origin {row['forecast_origin']}")
        ui.kpi(c[1], "Actual (approved)", f"{actual:,.0f}", target)
        ui.kpi(c[2], "Abs % error", f"{pe:.1f}%", f"error {err:+,.0f}")

        hist = s[s.index <= pd.Timestamp(target + "-01")]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist.index, y=hist.values, name="actual history", line=dict(color="#94a3b8")))
        fig.add_trace(go.Scatter(x=[pd.Timestamp(target + "-01")], y=[actual], name="actual", mode="markers",
                                 marker=dict(color="#16a34a", size=12)))
        fig.add_trace(go.Scatter(x=[pd.Timestamp(target + "-01")], y=[fc], name="saved forecast", mode="markers",
                                 marker=dict(color="#dc2626", size=12, symbol="x")))
        fig.update_layout(height=380, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

        # show the stored comparison rows for context
        conn = db.get_conn()
        comp = pd.read_sql_query(
            """SELECT c.category, c.actual_date, c.forecast_value, c.actual_value,
                      c.absolute_error, c.percentage_error
               FROM forecast_actual_comparisons c
               WHERE c.category=? ORDER BY c.actual_date DESC LIMIT 12""", conn, params=[cat])
        conn.close()
        if not comp.empty:
            st.markdown("##### Stored forecast-vs-actual comparison rows (recent)")
            st.dataframe(comp, use_container_width=True, hide_index=True)

st.divider()
with st.expander("Optional: demo recalculated forecast (NOT a saved previous forecast)"):
    st.caption("For illustration only. This recomputes a 1-step forecast live and is clearly NOT a "
               "previously saved forecast.")
    if len(s) >= C.INITIAL_TRAIN_MONTHS + 2 and st.button("Show demo recalculated forecast"):
        fc_demo = float(np.asarray(F.predict("Ensemble", s.values[:-1], 1, cat))[0])
        st.info(f"Demo recalculated forecast for {s.index[-1]:%Y-%m}: {fc_demo:,.0f} "
                f"(actual {float(s.values[-1]):,.0f}). **Demo recalculated forecast, not a saved previous forecast.**")
ui.practical_note()

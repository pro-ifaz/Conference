"""PHQ Reported-Crime Monitoring System — navigation router.
Run:  streamlit run app.py

The sidebar shows "Home" (not "app") because navigation is defined explicitly with
st.navigation / st.Page below. All existing pages are preserved.
"""
import sys
from pathlib import Path
import streamlit as st

# make project root importable (config, modules, utils)
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config as C
from modules.db import init_db

# allow the first set_page_config of this run to apply (see ui.py guard)
st.session_state.pop("_phq_page_config_done", None)
st.set_page_config(page_title=C.APP_NAME, page_icon="🛡️", layout="wide",
                   initial_sidebar_state="expanded")

# initialise DB + seed once
init_db()

P = "pages"
pages = [
    st.Page("home.py", title="Home", icon="🏠", default=True),
    st.Page(f"{P}/1_Dashboard.py", title="Dashboard", icon="📊"),
    st.Page(f"{P}/2_Add_Monthly_Data.py", title="Add Monthly Data", icon="📝"),
    st.Page(f"{P}/3_Validation_Report.py", title="Validation Report", icon="✅"),
    st.Page(f"{P}/4_Source_Provenance.py", title="Source Provenance", icon="🧾"),
    st.Page(f"{P}/5_Forecast_vs_Actual.py", title="Forecast vs Actual", icon="🎯"),
    st.Page(f"{P}/6_Model_Metrics.py", title="Model Metrics", icon="📐"),
    st.Page(f"{P}/7_Drift_Monitoring.py", title="Drift Monitoring", icon="📡"),
    st.Page(f"{P}/8_Rolling_Origin.py", title="Rolling-Origin", icon="🔁"),
    st.Page(f"{P}/9_Category_Stability.py", title="Category Stability", icon="🧩"),
    st.Page(f"{P}/10_Scenario_Projection.py", title="Scenario Projection", icon="🔮"),
    st.Page(f"{P}/11_Audit_Log.py", title="Audit Log", icon="🗂️"),
    st.Page(f"{P}/12_Export_Reports.py", title="Export Reports", icon="📦"),
    st.Page(f"{P}/13_Interpretability_XAI.py", title="Interpretability / XAI", icon="🔍"),
]

pg = st.navigation(pages, position="sidebar")
pg.run()

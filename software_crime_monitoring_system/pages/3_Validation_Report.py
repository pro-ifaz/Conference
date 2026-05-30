import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from utils import ui
st.set_page_config(page_title="Validation Report", page_icon="✅", layout="wide")
user = ui.require_login(); ui.header("Data validation report")
rep = st.session_state.get("last_validation")
if not rep:
    st.info("Run **Validate** on the *Add Monthly Data* page first."); st.stop()
s = rep["summary"]
c = st.columns(4)
ui.kpi(c[0], "Units entered", s["n_units"], f"missing {s['missing_units']} / extra {s['extra_units']}")
ui.kpi(c[1], "Missing cells", s["n_missing"], "should be 0")
ui.kpi(c[2], "Negative values", s["n_negative"], "should be 0")
ui.kpi(c[3], "Total mismatch rows", s["total_mismatch_rows"], "Total_Cases vs sum")
st.markdown("#### Failed (critical)")
[st.error(x) for x in rep["failed"]] or st.success("No critical failures.")
st.markdown("#### Warnings")
[st.warning(x) for x in rep["warnings"]] or st.caption("No warnings.")
st.markdown("#### Passed checks")
[st.success(x) for x in rep["passed"]]
st.divider()
st.markdown("**Approve eligibility:** " + ("✅ eligible (no critical errors)" if rep["can_approve"]
            else "❌ not eligible — fix critical errors"))

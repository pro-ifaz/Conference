"""Interpretability / XAI — read-only diagnostic views.

This page ONLY reads pre-computed XAI artifacts (PNG/CSV) from outputs/. It does NOT
recompute any XAI during Streamlit runtime, does not train models, and does not change
the forecasting model, validation, or reported accuracy. XAI here is diagnostic only.
"""
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as C
from utils import ui

st.set_page_config(page_title="Interpretability / XAI", page_icon="🔍", layout="wide")
user = ui.require_login()
ui.header("Explainable AI — supplementary diagnostics")

ui.practical_note()
st.info("**Diagnostic only.** These explainability views are read from pre-computed outputs. "
        "They explain feature influence and category-level error behavior. They do **not** change "
        "the forecasting model, the validation process, or any reported accuracy.")

FIG = C.OUTPUTS / "figures"
TAB = C.OUTPUTS / "tables"

def show_png(name, caption):
    p = FIG / name
    if p.exists():
        st.image(str(p), caption=caption, use_container_width=True)
    else:
        st.caption(f"({name} not bundled in this build)")

def show_csv(name, caption):
    p = TAB / name
    if p.exists():
        st.markdown(f"**{caption}**")
        try:
            st.dataframe(pd.read_csv(p), use_container_width=True, hide_index=True)
        except Exception as e:
            st.caption(f"(could not read {name}: {e})")
    else:
        st.caption(f"({name} not bundled in this build)")

tabs = st.tabs(["Feature importance", "Error contribution", "Category stability", "Residual diagnostics"])

with tabs[0]:
    ui.section("LightGBM feature importance")
    show_png("xai_lightgbm_feature_importance.png", "Influential lag / rolling / time features (diagnostic).")
    ui.section("Permutation importance")
    show_png("xai_permutation_importance.png", "Model-agnostic permutation importance check.")
    show_csv("xai_dashboard_feature_summary.csv", "Dashboard-ready feature summary")
    show_csv("xai_permutation_importance.csv", "Permutation importance values")

with tabs[1]:
    ui.section("Forecast error contribution by category")
    show_png("xai_error_contribution_by_category.png", "Share of total category MAE (diagnostic).")
    show_csv("xai_error_contribution_by_category.csv", "Error contribution table")

with tabs[2]:
    ui.section("Stable vs hard / noisy categories")
    show_csv("xai_category_stability_summary.csv", "Category stability summary")

with tabs[3]:
    ui.section("Residual diagnostics (statistical model)")
    show_png("xai_residual_diagnostics_total_cases.png",
             "ETS residual diagnostics for Total_Cases. Statistical models use residual diagnostics, not SHAP.")

st.divider()
st.caption("Source artifacts: outputs/figures/xai_*.png and outputs/tables/xai_*.csv. "
           "Generated offline in the thesis notebook (Section 14); not recomputed at runtime.")

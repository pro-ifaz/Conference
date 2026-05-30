"""Home page — login + landing overview.

Auth uses modules.auth (scrypt hashed passwords + optional env-var admin override + lockout).
The login hint that shows the seed credentials is hidden by default and only re-enabled by
setting PHQ_SHOW_LOGIN_HINT=1 in the environment (useful for thesis demos)."""
import sys
import time
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config as C
from modules import auth, db
from utils import ui

ui.header()

user = st.session_state.get("user")
if not user:
    st.subheader("🔐 Sign in")
    if C.SHOW_LOGIN_HINT:
        st.caption("Seed accounts — admin / operator / reviewer / viewer (default passwords end in `123`). "
                   "Re-deploy with PHQ_ADMIN_PASSWORD set and PHQ_SHOW_LOGIN_HINT=0 for production.")
    with st.form("login", clear_on_submit=False):
        u = st.text_input("Username", value="", autocomplete="username")
        p = st.text_input("Password", type="password", value="", autocomplete="current-password")
        ok = st.form_submit_button("Log in", use_container_width=True)
    if ok:
        uname = (u or "").strip()
        if not uname:
            st.error("Please enter your username.")
            st.stop()
        # lockout gate first
        locked, secs = auth.is_locked(st.session_state, uname)
        if locked:
            st.error(f"Too many failed attempts. Try again in {secs}s.")
            st.stop()
        conn = db.get_conn()
        try:
            rec = auth.authenticate(conn, uname, p or "")
        finally:
            conn.close()
        if rec is not None:
            auth.record_success(st.session_state, uname)
            st.session_state["user"] = rec
            st.success(f"Welcome, {rec['name']} ({rec['role']}).")
            st.rerun()
        else:
            now_locked, fails = auth.record_failure(st.session_state, uname)
            if now_locked:
                st.error(f"Account locked for {auth.LOCKOUT_DURATION_SECONDS // 60} minutes after "
                         f"{auth.LOCKOUT_MAX_FAILS} failed attempts. Please try later.")
            else:
                st.error(f"Invalid credentials. ({fails}/{auth.LOCKOUT_MAX_FAILS} attempts used.)")
            # small delay to slow scripted brute-force attempts
            time.sleep(0.5)
    st.stop()

# logged in -> landing overview
ui.sidebar_account()
st.success(f"Signed in as **{user['name']}** ({user['role']}).")

st.markdown("### Monthly operational monitoring loop")
st.markdown(
    """
    **PHQ monthly data release → data ingestion → cleaning & integrity audit → PHQ source
    provenance log → forecasting → actual-vs-forecast comparison → error dashboard &
    drift monitor → model recalibration → next forecast generation.**

    Use the **pages in the left sidebar** to walk the loop:
    """)
c1, c2 = st.columns(2)
c1.markdown(
    "- **Dashboard** — coverage, latest month, KPIs, drift status\n"
    "- **Add Monthly Data** — spreadsheet entry / CSV-XLSX import\n"
    "- **Validation Report** — integrity checks before approval\n"
    "- **Source Provenance** — PDF/URL + SHA-256\n"
    "- **Forecast vs Actual** — previous forecast vs newly added actual\n"
    "- **Model Metrics** — MAPE/sMAPE/MAE/RMSE/true_MASE/WAPE")
c2.markdown(
    "- **Drift Monitoring** — normal / warning / critical\n"
    "- **Rolling-Origin** — leakage-free, horizons 1/3/6/12\n"
    "- **Category Stability** — stable vs hard/noisy\n"
    "- **Scenario Projection** — future months (clearly labelled)\n"
    "- **Audit Log** — every add/edit/approve\n"
    "- **Export Reports** — CSV / XLSX / PDF\n"
    "- **Interpretability / XAI** — diagnostic feature/error views")

st.divider()
st.caption("This is an official PHQ reported-crime forecasting & monitoring framework for Bangladesh. "
           "It forecasts officially **reported**-crime counts (not hidden/unreported crime), does not "
           "claim perfect prediction, and never presents future scenario forecasts as verified results.")

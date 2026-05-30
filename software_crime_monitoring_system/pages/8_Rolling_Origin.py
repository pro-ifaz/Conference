"""Rolling-origin validation page.

Production note: in full (non-demo) mode this runs 8 models × up to 4 horizons × up to 5 folds
per category — about 5–15 s per category on the seed dataset. We don't run it on every page
load; instead we cache by (category, db_mtime) so the second visit to the same category is
instant, and a Recompute button forces a fresh run."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
import config as C
from modules import db, forecasting as F
from utils import ui

st.set_page_config(page_title="Rolling-Origin Validation", page_icon="🔁", layout="wide")
user = ui.require_login(); ui.header("Rolling-origin validation (leakage-free)")
st.markdown(f"""<div class="note">No random split · no future leakage · expanding window
(initial {C.INITIAL_TRAIN_MONTHS} months, step {C.CV_STEP}, up to {C.MAX_FOLDS} folds) ·
horizons {C.HORIZONS}. Model selection uses only data <b>before</b> each test fold.</div>""",
unsafe_allow_html=True)

cat = st.selectbox("Category", C.STABLE_CATEGORIES + C.HARD_CATEGORIES)
s = db.national_series(cat, approved_only=True)
if len(s) < C.INITIAL_TRAIN_MONTHS + 1:
    st.info("Not enough approved history."); st.stop()


def _db_mtime() -> float:
    try:
        return C.DB_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


@st.cache_data(show_spinner=False, ttl=900)
def _rolling(cat: str, series_bytes: bytes, _mtime: float) -> pd.DataFrame:
    """Cached rolling-origin for a single category. series_bytes is included so a change in the
    underlying data invalidates the cache automatically."""
    F.FALLBACK_LOG.clear()
    return F.rolling_origin(s, category=cat)


cc = st.columns([1, 1, 4])
recompute = cc[0].button("🔁 Recompute now")
if recompute:
    _rolling.clear()
with st.spinner("Computing rolling-origin metrics…"):
    cv = _rolling(cat, s.values.tobytes(), _db_mtime())

st.markdown("#### Model × horizon MAPE")
st.dataframe(cv.pivot_table(index="model", columns="horizon", values="MAPE").round(2),
             use_container_width=True)
st.markdown("#### Full metrics")
st.dataframe(cv[["model", "horizon", "n_folds", "MAPE", "sMAPE", "MAE", "RMSE", "true_MASE", "WAPE"]].round(2),
             use_container_width=True, height=380, hide_index=True)
flog = F.fallback_log_df()
st.markdown("#### Fallback log (auditable)")
st.dataframe(flog if len(flog) else pd.DataFrame({"note": ["no model fell back — all fit on all folds"]}),
             use_container_width=True, hide_index=True)

import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from modules import db
from utils import ui
st.set_page_config(page_title="Source Provenance", page_icon="🧾", layout="wide")
user = ui.require_login(); ui.header("PHQ source provenance log")
conn = db.get_conn()
df = pd.read_sql_query("SELECT year,month,phq_url,pdf_filename,sha256_checksum,uploaded_by,uploaded_at,verification_status,phq_statement_date,reviewer_note FROM crime_sources ORDER BY year DESC,month DESC", conn)
conn.close()
if df.empty:
    st.info("No source records yet. Attach a PHQ PDF/URL when adding a month."); st.stop()
st.caption("Each official PHQ statement is stored with its SHA-256 checksum for provenance integrity.")
st.dataframe(df, use_container_width=True, height=460, hide_index=True)

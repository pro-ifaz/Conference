import sys; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
import config as C
from modules import db, audit, export_reports as EX
from utils import ui
st.set_page_config(page_title="Export Reports", page_icon="📦", layout="wide")
user = ui.require_login(); ui.header("Export reports")
run = st.session_state.get("last_run")
nat = db.national_series("Total_Cases")
data_tbl = db.long_table(approved_only=True)
st.markdown("#### CSV / XLSX")
sheets = {"national_total_cases": nat.reset_index().rename(columns={"date":"Date",0:"Total_Cases"})
          if len(nat) else pd.DataFrame(), "audit_log": audit.fetch(2000)}
if run is not None:
    sheets["best_models"] = run["best"]; sheets["stability"] = run["stability"]
    sheets["next_forecast"] = run["next_forecast"]
st.download_button("⬇️ Full data (CSV)", EX.to_csv_bytes(data_tbl),
                   file_name="phq_monthly_data.csv", mime="text/csv")
st.download_button("⬇️ Workbook (XLSX)", EX.to_xlsx_bytes({k:v for k,v in sheets.items() if v is not None and len(v)}),
                   file_name="phq_monitoring_report.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.markdown("#### PDF summary report")
lines = [f"Coverage: {len(nat)} approved months",
         f"Latest month: {nat.index.max():%Y-%m}" if len(nat) else "no data",
         "ARCHIVED thesis verification: 92.5% practical accuracy (Total_Cases, Jun2025-Apr2026).",
         C.PRACTICAL_ACCURACY_NOTE, C.SCENARIO_WARNING]
if run is not None and len(run["best"]):
    lines.append("Live best-model stable mean MAPE by horizon:")
    hz = run["best"][run["best"].category.isin(C.STABLE_CATEGORIES)].groupby("horizon")["MAPE"].mean().round(2)
    lines += [f"  h={int(h)}: MAPE {v}" for h,v in hz.items()]
st.download_button("⬇️ Summary report (PDF)", EX.to_pdf_bytes("PHQ Monitoring Report", lines),
                   file_name="phq_monitoring_report.pdf", mime="application/pdf")

"""Add Monthly Data page — entry / CSV-XLSX upload + provenance + validate + approve.

Production hardening:
  - Default year/month auto-advance to the next expected month (latest approved + 1).
  - CSV upload handles UTF-8 / UTF-8-BOM / Latin-1 transparently.
  - Case-insensitive extension match (.CSV / .Xlsx work).
  - Column-name normalization (strips whitespace, fuzzy-maps common typos to PHQ standards).
  - After a successful approval + recalibration, the editor state is cleared so a stale draft
    from the previous month cannot accidentally be re-submitted.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io
import pandas as pd
import streamlit as st
import config as C
from modules import db, data_entry as DE, validation as V, provenance as P, audit, export_reports as EX
from utils import ui

st.set_page_config(page_title="Add Monthly Data", page_icon="📝", layout="wide")
user = ui.require_login()
ui.header("Add monthly PHQ data")

if not ui.can(user, "enter") and not ui.can(user, "import"):
    st.warning("Your role can view but not enter data. Switch to **operator** or **admin** to enter.")
    st.stop()

# ---- month selectors (auto-advance to next expected month) ----
default_y, default_m = db.next_expected_month()
top = st.columns([1, 1, 2])
year = top[0].number_input("Year", 2020, 2100, int(default_y), step=1)
month = top[1].selectbox("Month", list(range(1, 13)), index=int(default_m) - 1,
                         format_func=lambda m: pd.Timestamp(2000, m, 1).strftime("%B"))
ui.section("1 · Month & input method")
method = top[2].radio("Input method", ["Built-in manual table", "CSV / XLSX upload"], horizontal=True)

existing = set((int(r.year), int(r.month)) for _, r in db.months_present().iterrows())

ui.section("2 · Template & data"); st.markdown("##### Blank template")
tmpl = DE.build_template()
st.download_button("⬇️ Download blank template (CSV)", EX.to_csv_bytes(tmpl),
                   file_name=f"phq_template_{year}_{month:02d}.csv", mime="text/csv")


def _read_uploaded_table(upfile) -> pd.DataFrame:
    """Robust CSV/XLSX read: case-insensitive extension, multi-encoding CSV, BOM-safe."""
    name = upfile.name.lower()
    raw = upfile.getvalue()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(raw))
    # CSV path — try encodings in order. utf-8-sig strips BOM automatically.
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            # last resort: let pandas attempt with python engine
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc, engine="python")
            except Exception:
                continue
    raise ValueError(f"Could not read {upfile.name} as CSV or XLSX. Check the file format/encoding.")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace, collapse spaces, and fuzzy-map common typos to PHQ standard
    category names. Leaves anything we cannot map alone (validation will flag it)."""
    new_cols = []
    aliases = {
        # very common variants seen in PHQ exports / manual exports
        "total cases": "Total_Cases", "total": "Total_Cases", "total_cases": "Total_Cases",
        "speedy trial": "Speedy_Trial", "speedy_trial": "Speedy_Trial",
        "woman child repression": "Woman_Child_Repression", "wcr": "Woman_Child_Repression",
        "woman_child_repression": "Woman_Child_Repression",
        "police assault": "Police_Assault", "police_assault": "Police_Assault",
        "rc arms": "RC_Arms_Act", "rc_arms_act": "RC_Arms_Act",
        "rc explosive": "RC_Explosive_Act", "rc_explosive_act": "RC_Explosive_Act",
        "rc narcotics": "RC_Narcotics", "rc_narcotics": "RC_Narcotics",
        "rc smuggling": "RC_Smuggling", "rc_smuggling": "RC_Smuggling",
        "other cases": "Other_Cases", "other_cases": "Other_Cases",
        "unit name": "Unit", "police_unit": "Unit", "police unit": "Unit", "unit": "Unit",
    }
    for c in df.columns:
        if not isinstance(c, str):
            new_cols.append(c); continue
        key = " ".join(c.strip().lower().split())
        if key in aliases:
            new_cols.append(aliases[key])
        else:
            # title-case rebuild for casing typos only (keeps standard names intact)
            new_cols.append(c.strip())
    df = df.copy(); df.columns = new_cols
    return df


# ---- obtain the wide dataframe either by editing or upload ----
df_wide = None
if method == "Built-in manual table":
    st.markdown("##### Spreadsheet-like entry")
    st.caption("All 17 standard PHQ units (rows) and 15 categories (columns) are preloaded. "
               "Type numeric counts only; Total_Cases auto-calculates. Add custom rows/columns below.")
    base = st.session_state.get("entry_df")
    if base is None or st.button("Reset table"):
        base = DE.build_template()
        st.session_state["entry_df"] = base
    # custom fields
    with st.expander("➕ Flexible / custom entry (extra unit, district, range, or category)"):
        cc = st.columns(2)
        with cc[0]:
            new_unit = st.text_input("New unit / district / area name")
            new_unit_reason = st.text_input("Reason/note for new unit (required)")
            new_unit_map = st.selectbox("Map to standard PHQ unit (optional)",
                                        ["— none (excluded from model pipeline) —"] + C.STANDARD_UNITS)
            if st.button("Add unit row") and new_unit:
                if not new_unit_reason:
                    st.error("A reason/note is required to add a custom unit.")
                else:
                    mp = None if new_unit_map.startswith("—") else new_unit_map
                    DE.register_custom_unit(new_unit, "Custom", new_unit_reason, user["username"], mp)
                    d = st.session_state["entry_df"]
                    d.loc[len(d)] = [new_unit] + [0] * (d.shape[1] - 1)
                    st.session_state["entry_df"] = d
                    st.warning(f"Custom unit '{new_unit}' added. "
                               + ("Mapped to " + mp if mp else "NOT mapped → excluded from forecasting pipeline."))
        with cc[1]:
            new_cat = st.text_input("New crime category name")
            new_cat_reason = st.text_input("Reason/note for new category (required)")
            if st.button("Add category column") and new_cat:
                if not new_cat_reason:
                    st.error("A reason/note is required to add a custom category.")
                else:
                    DE.register_custom_category(new_cat, new_cat_reason, user["username"])
                    d = st.session_state["entry_df"]
                    if new_cat not in d.columns:
                        d.insert(len(d.columns) - 1, new_cat, 0)
                    st.session_state["entry_df"] = d
                    st.warning(f"Custom category '{new_cat}' added → excluded from pipeline unless mapped.")

    edited = st.data_editor(st.session_state["entry_df"], use_container_width=True,
                            num_rows="dynamic", key="editor", height=560)
    if st.button("🧮 Auto-calculate Total_Cases"):
        edited = DE.autocalc_total(edited)
        st.session_state["entry_df"] = edited
    df_wide = DE.autocalc_total(edited).set_index("Unit")

else:
    up = st.file_uploader("Upload monthly data (CSV or XLSX)", type=["csv", "xlsx"])
    if up:
        try:
            raw = _read_uploaded_table(up)
        except Exception as e:
            st.error(f"Could not parse upload: {e}")
            raw = None
        if raw is not None:
            raw = _normalize_columns(raw)
            st.markdown("**Preview (after column normalization)**")
            st.dataframe(raw.head(20), use_container_width=True, hide_index=True)
            # try to default the unit-column selector to "Unit" if it normalized to it
            default_unit_idx = list(raw.columns).index("Unit") if "Unit" in raw.columns else 0
            unit_col = st.selectbox("Which column holds the unit name?",
                                    list(raw.columns), index=default_unit_idx)
            raw = raw.rename(columns={unit_col: "Unit"})
            st.caption("Columns not matching a standard category are treated as custom "
                       "(excluded from pipeline unless mapped).")
            df_wide = DE.autocalc_total(raw).set_index("Unit")

# ---- provenance ----
ui.section("3 · Source provenance"); st.markdown("##### Source provenance (official PHQ statement)")
pc = st.columns([2, 1])
phq_url = pc[0].text_input("PHQ source URL", "https://www.police.gov.bd/en/")
pdf = pc[1].file_uploader("Official PDF (optional)", type=["pdf"])

# ---- validate / save ----
ui.section("4 · Validate & save"); st.markdown("##### Validate & save")
prev = None
nat_prev = db.national_series("Total_Cases")
if len(nat_prev):
    prev = {"Total_Cases": float(nat_prev.iloc[-1])}

if df_wide is not None and st.button("✅ Validate"):
    rep = V.validate_wide(df_wide.reset_index().set_index("Unit"), int(year), int(month), existing, prev)
    st.session_state["last_validation"] = rep
    if rep["failed"]:
        for f in rep["failed"]:
            st.error(f)
    for w in rep["warnings"]:
        st.warning(w)
    for p in rep["passed"]:
        st.success(p)
    st.info("Full report also on the **Validation Report** page.")

colA, colB = st.columns(2)
if df_wide is not None and colA.button("💾 Save as draft"):
    sid = None
    if pdf is not None or phq_url:
        sid, chk = P.save_source(int(year), int(month), phq_url,
                                 pdf.name if pdf else "", pdf.getvalue() if pdf else b"",
                                 user["username"])
    DE.save_month(df_wide.reset_index(), int(year), int(month), user["username"], sid, status="draft")
    db.invalidate_cache()
    st.success(f"Saved {year}-{month:02d} as draft (version created, audit-logged).")

if df_wide is not None and colB.button("📤 Submit for approval"):
    rep = st.session_state.get("last_validation") or V.validate_wide(
        df_wide.reset_index().set_index("Unit"), int(year), int(month), existing, prev)
    if not rep["can_approve"]:
        st.error("Cannot submit: critical validation errors remain. Fix them first.")
    else:
        sid = None
        if pdf is not None or phq_url:
            sid, chk = P.save_source(int(year), int(month), phq_url,
                                     pdf.name if pdf else "", pdf.getvalue() if pdf else b"",
                                     user["username"])
        DE.save_month(df_wide.reset_index(), int(year), int(month), user["username"], sid, status="submitted")
        db.invalidate_cache()
        st.success(f"Submitted {year}-{month:02d} for approval. A reviewer/admin can approve it below.")

# ---- approval + recalibration (admin/reviewer) ----
if ui.can(user, "approve"):
    st.divider()
    ui.section("5 · Approve & recalibrate"); st.markdown("##### Approve & recalibrate (admin/reviewer)")
    if st.button(f"Approve {int(year)}-{int(month):02d} and run recalibration"):
        try:
            DE.approve_month(int(year), int(month), user["username"])
        except ValueError as e:
            st.error(str(e))
            st.stop()
        db.invalidate_cache()
        from modules import recalibration as R
        with st.spinner("Refreshing rolling-origin validation, drift, and next forecast… "
                        "(full-mode recalibration takes ~60–120 s)"):
            res = R.recalibrate(run_type="post-approval", created_by=user["username"])
        db.invalidate_cache()
        st.session_state["last_run"] = res
        st.session_state["last_drift_status"] = res.get("overall_drift", "unknown")
        # clear the editor's draft so the operator doesn't re-submit the same month
        st.session_state.pop("entry_df", None)
        st.session_state.pop("last_validation", None)
        st.success(f"Approved and recalibrated. Run #{res['run_id']} · {res['runtime']}s · "
                   f"{len(res['fallback_log'])} fallback events. "
                   f"Overall drift status: **{res.get('overall_drift', 'unknown')}**.")
        if len(res["fallback_log"]):
            with st.expander("Fallback log (auditable)"):
                st.dataframe(res["fallback_log"], use_container_width=True, hide_index=True)
        st.info("👉 Next step: open **Forecast vs Actual** to see how the previously saved forecast "
                "compared to the newly approved month, or **Drift Monitoring** to review the new status.")

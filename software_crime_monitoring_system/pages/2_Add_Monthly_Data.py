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


def _show_clean_report(rep: dict):
    """Tell the user exactly what the import sanitiser removed/normalised (no silent loss)."""
    msgs = []
    if rep.get("empty_rows_dropped"):
        msgs.append(f"removed {rep['empty_rows_dropped']} fully-empty row(s)")
    if rep.get("blank_unit_rows_dropped"):
        msgs.append(f"removed {rep['blank_unit_rows_dropped']} row(s) with a blank unit name "
                    "(e.g. a trailing total row)")
    if rep.get("normalised_unit_names"):
        msgs.append(f"normalised {rep['normalised_unit_names']} unit label(s)")
    if msgs:
        st.info("🧹 Auto-cleaned on import: " + "; ".join(msgs) + ".")
    if rep.get("duplicate_units"):
        st.warning("⚠️ Duplicate unit row(s) detected — these would double-count: "
                   + ", ".join(map(str, rep["duplicate_units"]))
                   + ". Validation will block approval until you resolve them.")


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
    # Sanitise silently here (the editor is live, so blank in-progress rows are expected);
    # the Validate step still surfaces blank/duplicate units in the validation report.
    try:
        _cleaned, _ = DE.clean_uploaded_wide(edited)
        df_wide = DE.autocalc_total(_cleaned).set_index("Unit")
    except ValueError as e:
        st.error(str(e))
        df_wide = None

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
            try:
                cleaned, clean_rep = DE.clean_uploaded_wide(raw)
                _show_clean_report(clean_rep)
                if cleaned.empty:
                    st.error("After cleaning, no valid unit rows remain. Check the unit column "
                             "selection and the file contents.")
                    df_wide = None
                else:
                    df_wide = DE.autocalc_total(cleaned).set_index("Unit")
            except ValueError as e:
                st.error(str(e))
                df_wide = None

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

# ---- manage / delete / restore existing months (delete permission required) ----
if ui.can(user, "delete"):
    st.divider()
    ui.section("6 · Manage / delete existing months")
    st.markdown("##### Delete or restore a month")
    st.caption("**Soft delete** is reversible — the data is kept and can be restored later "
               "(recommended for fixing a bad import). **Hard delete** permanently removes the "
               "month and cannot be undone (admin only). Every action is audit-logged.")

    # one-time confirmation banner after an action (survives the rerun below)
    if st.session_state.get("_month_action_msg"):
        st.success(st.session_state.pop("_month_action_msg"))

    mtab = db.month_management_table()
    if mtab is None or mtab.empty:
        st.info("No months in the database yet.")
    else:
        show = mtab.assign(Month=[f"{int(y)}-{int(m):02d}" for y, m in zip(mtab.year, mtab.month)])
        st.dataframe(
            show[["Month", "state", "active_rows", "total_rows", "versions"]].rename(
                columns={"state": "Status", "active_rows": "Active rows",
                         "total_rows": "Total rows", "versions": "Versions"}),
            use_container_width=True, hide_index=True)

        opts = {f"{int(r.year)}-{int(r.month):02d}  ·  {r.state}": (int(r.year), int(r.month), r.state)
                for _, r in mtab.iterrows()}
        sel = st.selectbox("Select a month to manage", list(opts.keys()), key="mng_sel")
        sy, sm, sstate = opts[sel]
        token = f"{sy}-{sm:02d}"
        is_soft_deleted = (sstate == "deleted (soft)")

        if is_soft_deleted:
            st.info(f"**{token}** is currently soft-deleted (hidden from all forecasts and "
                    "dashboards). You can restore it below.")
            rreason = st.text_input("Reason / note (optional)", key="mng_restore_reason")
            rconf = st.text_input(f"Type `RESTORE {token}` to confirm", key="mng_restore_confirm")
            if st.button("♻️ Restore month", key="mng_restore_btn"):
                if rconf.strip() != f"RESTORE {token}":
                    st.error(f"Confirmation text must be exactly: RESTORE {token}")
                else:
                    try:
                        DE.restore_month(sy, sm, user["username"], reason=rreason)
                        db.invalidate_cache()
                        st.session_state["_month_changed"] = token
                        st.session_state["_month_action_msg"] = (
                            f"♻️ Restored {token}. Forecasts/drift are now stale — "
                            "re-run recalibration below.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        else:
            is_admin = str(user.get("role", "")).lower() == "admin"
            # deleting a month that is NOT the most recent active month leaves a gap in the
            # monthly time series, which seasonal models are sensitive to — flag it.
            active_mt = mtab[mtab["active_rows"] > 0]
            if not active_mt.empty:
                latest_active = active_mt.sort_values("date")[["year", "month"]].iloc[-1]
                if (int(latest_active["year"]), int(latest_active["month"])) != (sy, sm):
                    st.warning(f"Note: {token} is not the most recent month. Deleting it leaves a "
                               "gap in the monthly series — recalibrate afterwards and review drift.")
            mode = st.radio("Delete type", ["Soft delete (reversible)", "Hard delete (permanent)"],
                            key="mng_mode", horizontal=True)
            hard = mode.startswith("Hard")
            if hard and not is_admin:
                st.warning("Only an **admin** can perform a permanent hard delete. "
                           "Use soft delete, or sign in as admin.")
            dreason = st.text_input("Reason (required)", key="mng_del_reason",
                                    placeholder="e.g. wrong source file, re-importing corrected data")
            dconf = st.text_input(f"Type `DELETE {token}` to confirm", key="mng_del_confirm")
            if st.button("🗑️ Delete month", key="mng_del_btn", disabled=(hard and not is_admin)):
                if not dreason.strip():
                    st.error("A reason is required to delete a month.")
                elif dconf.strip() != f"DELETE {token}":
                    st.error(f"Confirmation text must be exactly: DELETE {token}")
                else:
                    try:
                        res = DE.delete_month(sy, sm, user["username"], reason=dreason, hard=hard)
                        db.invalidate_cache()
                        st.session_state["_month_changed"] = token
                        kind = "🗑️ Permanently deleted" if res["hard"] else "🗂️ Soft-deleted"
                        tail = ("" if res["hard"]
                                else " You can restore it from this panel at any time.")
                        st.session_state["_month_action_msg"] = (
                            f"{kind} {token} ({res['deleted_rows']} row(s)).{tail}")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    # offer recalibration after any delete/restore (totals changed → forecasts/drift stale)
    if st.session_state.get("_month_changed"):
        st.warning(f"Data changed for **{st.session_state['_month_changed']}** — forecasts, drift "
                   "and metrics are now stale.")
        cols = st.columns([1, 1])
        if ui.can(user, "recalibrate") and cols[0].button("🔄 Run recalibration now",
                                                           key="mng_recal_btn"):
            from modules import recalibration as R
            with st.spinner("Refreshing rolling-origin validation, drift, and next forecast… "
                            "(full-mode recalibration takes ~60–120 s)"):
                rr = R.recalibrate(run_type="post-delete", created_by=user["username"])
            db.invalidate_cache()
            st.session_state["last_run"] = rr
            st.session_state["last_drift_status"] = rr.get("overall_drift", "unknown")
            st.session_state.pop("_month_changed", None)
            st.success(f"Recalibrated. Run #{rr['run_id']} · {rr['runtime']}s · "
                       f"overall drift status: **{rr.get('overall_drift', 'unknown')}**.")
        if cols[1].button("Dismiss", key="mng_dismiss_btn"):
            st.session_state.pop("_month_changed", None)
            st.rerun()

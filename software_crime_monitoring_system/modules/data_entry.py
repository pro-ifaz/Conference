"""Data-entry helpers: build the editable template, manage custom fields, save a month."""
import pandas as pd
import config as C
from .db import get_conn, _now
from . import audit


def build_template(units=None, categories=None) -> pd.DataFrame:
    """Wide editable table: rows=units, cols=categories, all zeros + Total_Cases col."""
    units = units or C.STANDARD_UNITS
    categories = categories or C.STANDARD_CATEGORIES
    df = pd.DataFrame(0, index=units, columns=categories, dtype="int64")
    df["Total_Cases"] = 0
    df.index.name = "Unit"
    return df.reset_index()


def autocalc_total(df_wide: pd.DataFrame) -> pd.DataFrame:
    cats = [c for c in df_wide.columns if c not in ("Unit", "Total_Cases")
            and c in C.STANDARD_CATEGORIES]
    df = df_wide.copy()
    df["Total_Cases"] = df[cats].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1).astype(int)
    return df


def _clean_unit_label(v) -> str:
    """Coerce a unit cell to a clean string. NaN/None -> '' ; 2024.0 -> '2024' ; '  DMP ' -> 'DMP'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (int, float)) and float(v).is_integer():
        return str(int(v))
    return str(v).strip()


def clean_uploaded_wide(df: pd.DataFrame):
    """Sanitise a freshly-read wide table BEFORE validation/saving.

    Real-world PHQ exports routinely carry trailing total rows, blank rows from merged
    cells, stray numeric identifiers in the unit column, and whitespace. Left untouched
    these (a) crash str.join() in validation and (b) get written to the DB as junk units.

    Returns (clean_df, report) where report summarises what was removed/normalised so the
    UI can tell the user exactly what happened (no silent data loss).
    """
    report = {"empty_rows_dropped": 0, "blank_unit_rows_dropped": 0,
              "duplicate_units": [], "normalised_unit_names": 0}
    if "Unit" not in df.columns:
        raise ValueError("No 'Unit' column found — pick the column that holds the unit name first.")
    df = df.copy()

    # 1) drop fully-empty rows (every cell NaN)
    before = len(df)
    df = df.dropna(how="all")
    report["empty_rows_dropped"] = before - len(df)

    # 2) normalise the unit column to clean strings
    original = df["Unit"].astype(object)
    cleaned = original.map(_clean_unit_label)
    report["normalised_unit_names"] = int(
        sum(1 for a, b in zip(original.tolist(), cleaned.tolist())
            if (("" if (a is None or (isinstance(a, float) and pd.isna(a))) else str(a)) != b)))
    df["Unit"] = cleaned

    # 3) drop rows whose unit is blank after cleaning (trailing total / empty-name rows)
    blank_mask = df["Unit"].str.len() == 0
    report["blank_unit_rows_dropped"] = int(blank_mask.sum())
    df = df[~blank_mask]

    # 4) report duplicate units (NOT auto-merged — validation will block so the user decides)
    if len(df):
        dups = df["Unit"][df["Unit"].duplicated(keep=False)].unique().tolist()
        report["duplicate_units"] = dups

    return df.reset_index(drop=True), report


def register_custom_unit(name, unit_type, reason, created_by, mapped_to=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT OR IGNORE INTO reporting_units
        (unit_name,unit_type,is_standard_phq_unit,is_active,mapped_to,created_by,created_at,note)
        VALUES(?,?,?,?,?,?,?,?)""",
        (name, unit_type or "Custom", 0, 1, mapped_to, created_by, _now(), reason))
    conn.commit(); conn.close()
    audit.log("add_custom_unit", "reporting_units", name, new_value=name, changed_by=created_by,
              reason=reason, affected_unit=name, custom_field_flag=1)


def register_custom_category(name, reason, created_by, mapped_to=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT OR IGNORE INTO crime_categories
        (category_name,display_name,is_standard_phq_category,is_model_supported,is_active,mapped_to,created_by,created_at,note)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (name, name.replace("_", " "), 0, 0, 1, mapped_to, created_by, _now(), reason))
    conn.commit(); conn.close()
    audit.log("add_custom_category", "crime_categories", name, new_value=name, changed_by=created_by,
              reason=reason, affected_category=name, custom_field_flag=1)


def save_month(df_wide: pd.DataFrame, year, month, created_by, source_id=None, status="draft"):
    """Persist a wide table as long rows. Custom/unmapped fields excluded from pipeline."""
    df = autocalc_total(df_wide)
    cats = [c for c in df.columns if c not in ("Unit", "Total_Cases")]
    date = f"{year}-{month:02d}-01"
    conn = get_conn(); cur = conn.cursor()
    # version
    vn = cur.execute("SELECT COALESCE(MAX(version_number),0)+1 FROM data_versions WHERE year=? AND month=?",
                     (year, month)).fetchone()[0]
    cur.execute("""INSERT INTO data_versions(year,month,version_number,status,created_by,created_at,change_summary)
                   VALUES(?,?,?,?,?,?,?)""", (year, month, vn, status, created_by, _now(),
                                              f"entry v{vn} ({status})"))
    vid = cur.lastrowid
    std_units = set(C.STANDARD_UNITS); std_cats = set(C.STANDARD_CATEGORIES)
    rows = []
    skipped_blank = 0
    for _, r in df.iterrows():
        unit = _clean_unit_label(r["Unit"])
        if unit == "":
            skipped_blank += 1  # never persist a blank/NaN unit row
            continue
        is_cu = int(unit not in std_units)
        total = float(pd.to_numeric(r["Total_Cases"], errors="coerce") or 0)
        for c in cats:
            is_cc = int(c not in std_cats)
            in_pipe = int(is_cu == 0 and is_cc == 0)  # only standard fields enter pipeline
            rows.append((year, month, date, unit, c, float(pd.to_numeric(r[c], errors="coerce") or 0),
                         total, source_id, vid, created_by, _now(), _now(), status,
                         is_cu, is_cc, in_pipe, None))
    cur.executemany("""INSERT INTO crime_monthly_data
        (year,month,date,police_unit,crime_category,value,total_cases,source_id,version_id,
         created_by,created_at,updated_at,verification_status,is_custom_unit,is_custom_category,
         in_model_pipeline,custom_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit(); conn.close()
    note = f"data entry v{vn}" + (f"; skipped {skipped_blank} blank-unit row(s)" if skipped_blank else "")
    audit.log("save_month", "crime_monthly_data", f"{year}-{month:02d}", new_value=f"{len(rows)} rows ({status})",
              changed_by=created_by, reason=note, affected_year=year, affected_month=month)
    return vid


def approve_month(year, month, approved_by, version_id=None):
    """Approve ONE version for a (year,month) and make it the only active one.
    Prevents double-counting: all other versions for that month are deactivated."""
    conn = get_conn(); cur = conn.cursor()
    if version_id is None:  # default: approve the latest entered version for the month
        row = cur.execute(
            "SELECT MAX(version_id) FROM crime_monthly_data WHERE year=? AND month=?",
            (year, month)).fetchone()
        version_id = row[0]
    if version_id is None:
        conn.close()
        raise ValueError(f"No data found for {year}-{month:02d} to approve.")
    # deactivate every other version of this month; activate + approve the chosen one
    cur.execute("""UPDATE crime_monthly_data SET is_active=0
                   WHERE year=? AND month=? AND version_id<>?""", (year, month, version_id))
    cur.execute("""UPDATE crime_monthly_data
                   SET verification_status='approved', is_active=1 WHERE version_id=?""", (version_id,))
    cur.execute("""UPDATE data_versions SET status='superseded'
                   WHERE year=? AND month=? AND version_id<>? AND status='approved'""",
                (year, month, version_id))
    cur.execute("""UPDATE data_versions SET status='approved', approved_by=?, approved_at=?
                   WHERE version_id=?""", (approved_by, _now(), version_id))
    conn.commit(); conn.close()
    audit.log("approve_month", "data_versions", f"{year}-{month:02d}",
              new_value=f"approved version_id={version_id}; others deactivated",
              changed_by=approved_by, reason="month approved (single active version)",
              affected_year=year, affected_month=month)
    return version_id


def delete_month(year, month, deleted_by, reason, hard=False):
    """Delete a month's data.

    Soft delete (default, reversible): every row for the month is deactivated
    (is_active=0) and its data_versions are flagged 'deleted'. The history stays in the
    DB and the month can be brought back with restore_month — this is the recommended,
    audit-friendly path for correcting a bad import.

    Hard delete (admin-only, permanent): physically removes the month's rows and version
    records. The pre-delete totals are captured in the audit log so the action is traceable
    even though the underlying rows are gone.

    A non-empty `reason` is required. Raises ValueError if the month has no data.
    """
    if not reason or not str(reason).strip():
        raise ValueError("A reason is required to delete a month.")
    conn = get_conn(); cur = conn.cursor()
    stats = cur.execute(
        "SELECT COUNT(*) total_rows, "
        "SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) active_rows, "
        "COALESCE(SUM(CASE WHEN is_active=1 THEN value ELSE 0 END),0) active_value "
        "FROM crime_monthly_data WHERE year=? AND month=?", (year, month)).fetchone()
    total_rows = int(stats[0] or 0)
    if total_rows == 0:
        conn.close()
        raise ValueError(f"No data found for {year}-{month:02d} to delete.")
    active_rows = int(stats[1] or 0)
    active_value = float(stats[2] or 0.0)

    if hard:
        cur.execute("DELETE FROM crime_monthly_data WHERE year=? AND month=?", (year, month))
        cur.execute("DELETE FROM data_versions WHERE year=? AND month=?", (year, month))
        action, summary = "hard_delete_month", (
            f"PERMANENTLY removed {total_rows} row(s) "
            f"(active total_cases sum at delete ≈ {active_value:.0f})")
    else:
        cur.execute("UPDATE crime_monthly_data SET is_active=0, updated_at=? "
                    "WHERE year=? AND month=?", (_now(), year, month))
        cur.execute("UPDATE data_versions SET status='deleted' WHERE year=? AND month=?",
                    (year, month))
        action, summary = "soft_delete_month", (
            f"deactivated {active_rows} active row(s) of {total_rows} total (reversible)")
    conn.commit(); conn.close()
    audit.log(action, "crime_monthly_data", f"{year}-{month:02d}",
              old_value=f"{active_rows} active row(s)", new_value=summary,
              changed_by=deleted_by, reason=str(reason).strip(),
              affected_year=year, affected_month=month)
    return {"deleted_rows": total_rows, "active_rows": active_rows, "hard": bool(hard)}


def restore_month(year, month, restored_by, reason=""):
    """Reverse a soft delete: reactivate the latest version of a previously soft-deleted month.

    Only one version is reactivated (the highest version_id) so totals can never double-count,
    mirroring approve_month. Raises ValueError if the month is already active or if no rows
    exist (e.g. it was hard-deleted)."""
    conn = get_conn(); cur = conn.cursor()
    vids = [r[0] for r in cur.execute(
        "SELECT DISTINCT version_id FROM crime_monthly_data WHERE year=? AND month=?",
        (year, month)).fetchall()]
    if not vids:
        conn.close()
        raise ValueError(f"No data exists for {year}-{month:02d} to restore "
                         "(a hard delete cannot be undone).")
    active = cur.execute(
        "SELECT COUNT(*) FROM crime_monthly_data WHERE year=? AND month=? AND is_active=1",
        (year, month)).fetchone()[0]
    if active > 0:
        conn.close()
        raise ValueError(f"{year}-{month:02d} is already active — nothing to restore.")
    latest = max(v for v in vids if v is not None)
    cur.execute("UPDATE crime_monthly_data SET is_active=0 WHERE year=? AND month=?", (year, month))
    cur.execute("UPDATE crime_monthly_data SET is_active=1, updated_at=? WHERE version_id=?",
                (_now(), latest))
    vs = cur.execute("SELECT verification_status FROM crime_monthly_data WHERE version_id=? LIMIT 1",
                     (latest,)).fetchone()
    row_status = (vs[0] if vs else "submitted") or "submitted"
    dv_status = "approved" if row_status == "approved" else row_status
    cur.execute("UPDATE data_versions SET status=? WHERE year=? AND month=? AND version_id=?",
                (dv_status, year, month, latest))
    cur.execute("UPDATE data_versions SET status='superseded' "
                "WHERE year=? AND month=? AND version_id<>?", (year, month, latest))
    conn.commit(); conn.close()
    audit.log("restore_month", "crime_monthly_data", f"{year}-{month:02d}",
              new_value=f"reactivated version_id={latest} (status={dv_status})",
              changed_by=restored_by, reason=(str(reason).strip() or "month restored from soft delete"),
              affected_year=year, affected_month=month)
    return {"restored_version_id": latest, "status": dv_status}

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
    for _, r in df.iterrows():
        unit = r["Unit"]; is_cu = int(unit not in std_units)
        total = float(r["Total_Cases"])
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
    audit.log("save_month", "crime_monthly_data", f"{year}-{month:02d}", new_value=f"{len(rows)} rows ({status})",
              changed_by=created_by, reason=f"data entry v{vn}", affected_year=year, affected_month=month)
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

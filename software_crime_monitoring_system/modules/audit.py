"""Append-only audit logging."""
from .db import get_conn, _now


def log(action, table_name="", record_id="", old_value="", new_value="", changed_by="system",
        reason="", source_id=None, affected_year=None, affected_month=None,
        affected_unit=None, affected_category=None, custom_field_flag=0):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO audit_logs
        (table_name,record_id,action,old_value,new_value,changed_by,changed_at,reason,source_id,
         affected_year,affected_month,affected_unit,affected_category,custom_field_flag)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (table_name, str(record_id), action, str(old_value)[:500], str(new_value)[:500],
         changed_by, _now(), reason, source_id, affected_year, affected_month,
         affected_unit, affected_category, int(custom_field_flag)))
    conn.commit(); conn.close()


def fetch(limit=500):
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM audit_logs ORDER BY audit_id DESC LIMIT ?", conn, params=[limit])
    conn.close(); return df

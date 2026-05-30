"""Source provenance: checksum + storage of PHQ source PDF / URL."""
import hashlib
from datetime import datetime
import config as C
from .db import get_conn, _now


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256(); h.update(data); return h.hexdigest()


def save_source(year, month, phq_url, pdf_filename, pdf_bytes, uploaded_by,
                reviewer_note="", phq_statement_date=""):
    checksum, path = "", ""
    if pdf_bytes:
        checksum = sha256_bytes(pdf_bytes)
        path = str(C.UPLOADS / f"{year}-{month:02d}_{pdf_filename}")
        with open(path, "wb") as f:
            f.write(pdf_bytes)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""INSERT INTO crime_sources
        (year,month,phq_url,pdf_filename,pdf_path,sha256_checksum,uploaded_by,uploaded_at,
         verification_status,reviewer_note,phq_statement_date)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (year, month, phq_url, pdf_filename, path, checksum, uploaded_by, _now(),
         "pending", reviewer_note, phq_statement_date))
    sid = cur.lastrowid; conn.commit(); conn.close()
    return sid, checksum

"""Export tables to CSV / XLSX and a simple PDF text report."""
import io
import pandas as pd
import config as C


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
    return buf.getvalue()


def to_pdf_bytes(title: str, lines: list[str]) -> bytes:
    """Minimal dependency-light PDF (reportlab if available, else a .txt fallback as bytes)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        y = h - 50
        c.setFont("Helvetica-Bold", 14); c.drawString(40, y, title[:90]); y -= 26
        c.setFont("Helvetica", 9)
        for ln in lines:
            for chunk in [ln[i:i+95] for i in range(0, len(ln), 95)] or [""]:
                if y < 50:
                    c.showPage(); y = h - 50; c.setFont("Helvetica", 9)
                c.drawString(40, y, chunk); y -= 13
        c.showPage(); c.save()
        return buf.getvalue()
    except Exception:
        return ("PDF engine unavailable; plain text report.\n\n" + title + "\n\n" + "\n".join(lines)).encode("utf-8")

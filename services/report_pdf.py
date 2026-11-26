from datetime import date
from fpdf import FPDF

COMPANY = "Snack Manufacturing Factory"


def _clean(text):
    """The built-in PDF fonts only know latin-1 characters."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _fit(pdf, text, width):
    """Cut the text so it fits inside its cell."""
    text = _clean(text)
    limit = width - 2
    if pdf.get_string_width(text) <= limit:
        return text
    while text and pdf.get_string_width(text + "...") > limit:
        text = text[:-1]
    return text + "..."


def _is_number(text):
    t = str(text).replace(",", "").replace("-", "").replace(".", "").replace("%", "")
    return t.isdigit()


def table_pdf(title, subtitle, headers, rows, weights=None):
    """Make a landscape A4 PDF with one table. Returns the PDF as bytes."""
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    weights = weights or [1] * len(headers)
    widths = [pdf.epw * w / sum(weights) for w in weights]
    row_h = 7

    def header_row():
        pdf.set_fill_color(79, 70, 229)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        for w, h in zip(widths, headers):
            pdf.cell(w, row_h, _fit(pdf, h, w), border=1, align="C", fill=True)
        pdf.ln(row_h)
        pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, _clean(COMPANY), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _clean(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _clean(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    header_row()

    for row in rows:
        if pdf.get_y() + row_h > pdf.h - 15:
            pdf.add_page()
            header_row()
        bold = any(str(c).upper() == "TOTAL" for c in row)
        pdf.set_font("Helvetica", "B" if bold else "", 9)
        for w, cell in zip(widths, row):
            align = "R" if _is_number(cell) else "L"
            pdf.cell(w, row_h, _fit(pdf, cell, w), border=1, align=align)
        pdf.ln(row_h)

    if not rows:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 8, "No data for this period", border=1, new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(-12)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "Generated on " + date.today().isoformat(), align="C")
    return bytes(pdf.output())
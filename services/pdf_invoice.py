from fpdf import FPDF
from services.gst import rupees, FACTORY_STATE

# Demo seller details (assumption: written in the README)
SELLER_NAME = "SnackFlow ERP"
SELLER_TAGLINE = "Order-to-Audit Management System for Snack Manufacturing"
SELLER_GSTIN = "33AAAAA9999A1Z5"
SELLER_ADDRESS = "Tiruchirappalli, Tamil Nadu"


def _line(pdf, text, h=5, bold=False, align="L"):
    pdf.set_font("Helvetica", "B" if bold else "", 10)
    pdf.cell(0, h, text, align=align, new_x="LMARGIN", new_y="NEXT")


def _total(pdf, label, value, bold=False):
    pdf.set_font("Helvetica", "B" if bold else "", 10)
    pdf.cell(140, 7, label, align="R")
    pdf.cell(40, 7, value, border=1, align="R", new_x="LMARGIN", new_y="NEXT")


def build_invoice_pdf(conn, invoice_id):
    """Returns the invoice as PDF bytes, or None if the invoice does not exist."""
    inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if inv is None:
        return None
    cust = conn.execute("SELECT * FROM customers WHERE id = ?", (inv["customer_id"],)).fetchone()
    lines = conn.execute(
        "SELECT ol.qty_ordered, ol.rate_paise, ol.gst_percent, i.name, i.hsn_code "
        "FROM order_lines ol JOIN items i ON i.id = ol.item_id WHERE ol.order_id = ?",
        (inv["order_id"],),
    ).fetchall()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(True, 15)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, "TAX INVOICE", align="C", new_x="LMARGIN", new_y="NEXT")
    _line(pdf, SELLER_NAME, 6, bold=True)
    _line(pdf, SELLER_TAGLINE)
    _line(pdf, SELLER_ADDRESS)
    _line(pdf, f"GSTIN: {SELLER_GSTIN}   |   State: {FACTORY_STATE}")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 5, f"Invoice No: {inv['invoice_no']}")
    pdf.cell(0, 5, f"Date: {inv['invoice_date']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    _line(pdf, "Bill to", 6, bold=True)
    _line(pdf, cust["name"])
    _line(pdf, f"GSTIN: {cust['gstin'] or 'Unregistered'}")
    _line(pdf, f"Place of supply: {cust['state']}")
    pdf.ln(4)

    widths = [55, 20, 20, 30, 35, 20]
    heads = ["Item", "HSN", "Qty", "Rate", "Taxable", "GST %"]
    pdf.set_fill_color(91, 60, 196)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    for w, h in zip(widths, heads):
        pdf.cell(w, 7, h, border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    for l in lines:
        taxable = l["qty_ordered"] * l["rate_paise"]
        cells = [l["name"], l["hsn_code"] or "-", str(l["qty_ordered"]),
                 rupees(l["rate_paise"]), rupees(taxable), f"{l['gst_percent']}%"]
        for w, text in zip(widths, cells):
            pdf.cell(w, 7, text, border=1)
        pdf.ln()

    pdf.ln(3)
    _total(pdf, "Taxable value", rupees(inv["taxable_paise"]))
    if inv["igst_paise"] > 0:
        _total(pdf, "IGST", rupees(inv["igst_paise"]))
    else:
        _total(pdf, "CGST", rupees(inv["cgst_paise"]))
        _total(pdf, "SGST", rupees(inv["sgst_paise"]))
    _total(pdf, "Invoice total", rupees(inv["total_paise"]), bold=True)

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 5, "This is a computer generated invoice (demo data).", align="C")
    return bytes(pdf.output())
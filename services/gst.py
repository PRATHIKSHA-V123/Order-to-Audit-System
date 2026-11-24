from decimal import Decimal, ROUND_HALF_UP

FACTORY_STATE = "Tamil Nadu"


def rupees(paise):
    """Show paise as rupees, e.g. 787500 -> Rs 7,875.00"""
    value = (Decimal(paise) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return f"Rs {value:,.2f}"


def calc_tax(taxable_paise, gst_percent, customer_state):
    """
    Returns (cgst, sgst, igst) in paise.
    Same state as the factory -> CGST + SGST. Other state -> IGST.
    """
    tax = Decimal(taxable_paise) * gst_percent / 100
    tax = int(tax.quantize(Decimal("1"), ROUND_HALF_UP))
    if customer_state == FACTORY_STATE:
        cgst = tax // 2
        sgst = tax - cgst
        return cgst, sgst, 0
    return 0, 0, tax


def financial_year(date_str):
    """'2026-11-19' -> '2026-27' (the financial year starts in April)."""
    year, month = int(date_str[:4]), int(date_str[5:7])
    start = year if month >= 4 else year - 1
    return f"{start}-{str(start + 1)[2:]}"


def next_invoice_no(conn, date_str):
    """Invoice numbers run by financial year: INV/2026-27/0001"""
    prefix = f"INV/{financial_year(date_str)}/"
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM invoices WHERE invoice_no LIKE ?", (prefix + "%",)
    ).fetchone()["c"]
    return f"{prefix}{count + 1:04d}"
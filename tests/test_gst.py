from services.gst import calc_tax, financial_year, rupees, next_invoice_no


def test_tamil_nadu_gets_cgst_and_sgst():
    assert calc_tax(750000, 5, "Tamil Nadu") == (18750, 18750, 0)


def test_other_state_gets_igst():
    assert calc_tax(600000, 5, "Karnataka") == (0, 0, 30000)


def test_odd_paise_split_adds_up():
    cgst, sgst, igst = calc_tax(10100, 5, "Tamil Nadu")
    assert cgst + sgst == 505 and igst == 0


def test_financial_year_starts_in_april():
    assert financial_year("2026-11-19") == "2026-27"
    assert financial_year("2026-03-31") == "2025-26"
    assert financial_year("2026-04-01") == "2026-27"


def test_rupees_format():
    assert rupees(787500) == "Rs 7,875.00"
    assert rupees(18750) == "Rs 187.50"


def test_invoice_numbers_run_by_financial_year(conn):
    assert next_invoice_no(conn, "2026-11-19") == "INV/2026-27/0001"
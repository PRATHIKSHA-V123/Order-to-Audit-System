from decimal import Decimal
import pytest
from services.stock import balance, record_purchase
from services.production import record_run, run_report
from services.orders import (create_order, stock_check, approve_order, invoice_order,
                             dispatch_order, record_payment, invoice_outstanding)
from services.gst import calc_tax
from services.costing import run_cost


def ids(conn):
    return {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM items")}


def customers(conn):
    return {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM customers")}


def produce(conn):
    """Benchmark steps 1 to 3: purchase, then one production run."""
    i = ids(conn)
    record_purchase(conn, i["Flour"], 60000, 270000)
    used = {i["Flour"]: 40000, i["Cooking oil"]: 10500, i["Salt and spice mix"]: 1200,
            i["200 g pouch"]: 194, i["Carton (20 packets)"]: 9}
    damaged = {i["200 g pouch"]: 6}
    run_id = record_run(conn, i["Murukku 200 g"], 1, used, 188, damaged=damaged,
                        labour_paise=120000, overhead_paise=60000)
    return i, run_id


def test_stock_after_production(conn):
    i, _ = produce(conn)
    assert balance(conn, i["Flour"]) == 120000            # 120 kg
    assert balance(conn, i["Cooking oil"]) == 19500       # 19.5 L
    assert balance(conn, i["200 g pouch"]) == 306
    assert balance(conn, i["Murukku 200 g"]) == 238


def test_variance_flags(conn):
    _, run_id = produce(conn)
    report = run_report(conn, run_id)
    assert report["yield_pct"] == Decimal("-6.00") and report["yield_flag"]
    lines = {l["name"]: l for l in report["lines"]}
    assert lines["Cooking oil"]["pct"] == Decimal("5.00") and lines["Cooking oil"]["flag"]
    assert lines["200 g pouch"]["pct"] == Decimal("-3.00") and not lines["200 g pouch"]["flag"]


def test_retailer_a_invoice_dispatch_and_payment(conn):
    i, _ = produce(conn)
    c = customers(conn)
    order = create_order(conn, c["Retailer A"], [(i["Murukku 200 g"], 150)])
    assert stock_check(conn, order)[0]["shortage"] == 0
    approve_order(conn, order)
    inv_id = invoice_order(conn, order)
    inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,)).fetchone()
    assert (inv["taxable_paise"], inv["cgst_paise"], inv["sgst_paise"], inv["igst_paise"],
            inv["total_paise"]) == (750000, 18750, 18750, 0, 787500)

    dispatch_order(conn, order)
    assert balance(conn, i["Murukku 200 g"]) == 88

    record_payment(conn, inv_id, 400000)
    assert invoice_outstanding(conn, inv_id) == 387500
    with pytest.raises(ValueError):
        record_payment(conn, inv_id, 400000)              # more than outstanding


def test_distributor_b_shortage_blocks_invoice(conn):
    i, _ = produce(conn)
    c = customers(conn)
    a = create_order(conn, c["Retailer A"], [(i["Murukku 200 g"], 150)])
    approve_order(conn, a)
    invoice_order(conn, a)
    dispatch_order(conn, a)

    b = create_order(conn, c["Distributor B"], [(i["Murukku 200 g"], 120)])
    assert stock_check(conn, b)[0]["shortage"] == 32
    approve_order(conn, b)
    with pytest.raises(ValueError):
        invoice_order(conn, b)
    assert calc_tax(120 * 5000, 5, "Karnataka") == (0, 0, 30000)   # IGST would apply


def test_cost_per_packet(conn):
    _, run_id = produce(conn)
    cost = run_cost(conn, run_id)
    assert cost["material"] == 405500                     # Rs 4,055.00
    assert cost["total"] == 585500                        # plus labour and gas/power
    assert cost["per_packet"] == Decimal("3114.36")       # Rs 31.14 per packet
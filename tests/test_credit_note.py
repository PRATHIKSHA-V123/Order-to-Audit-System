import pytest
from services.stock import balance
from services.orders import (create_order, approve_order, invoice_order,
                             dispatch_order, cancel_invoice)


def test_credit_note_cancels_invoice_and_returns_stock(conn):
    fg = conn.execute("SELECT id FROM items WHERE name = 'Murukku 200 g'").fetchone()["id"]
    cust = conn.execute("SELECT id FROM customers WHERE name = 'Retailer A'").fetchone()["id"]
    order = create_order(conn, cust, [(fg, 10)])
    approve_order(conn, order)
    inv_id = invoice_order(conn, order)
    dispatch_order(conn, order)
    assert balance(conn, fg) == 40

    cn_id = cancel_invoice(conn, order, "Wrong quantity")
    assert balance(conn, fg) == 50                                  # stock came back
    cn = conn.execute("SELECT * FROM credit_notes WHERE id = ?", (cn_id,)).fetchone()
    assert cn["total_paise"] == 52500                               # 10 x Rs 50 + 5% GST
    still = conn.execute("SELECT COUNT(*) AS c FROM invoices WHERE id = ?", (inv_id,)).fetchone()
    assert still["c"] == 1                                          # invoice is never deleted
    with pytest.raises(ValueError):
        cancel_invoice(conn, order, "again")                        # cannot cancel twice
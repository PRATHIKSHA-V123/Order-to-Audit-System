from datetime import date
from services.stock import balance, add_movement
from services.gst import calc_tax, next_invoice_no


def create_order(conn, customer_id, lines, user_id=None):
    """lines = [(item_id, qty), ...]. Price and GST come from the item master."""
    cur = conn.execute(
        "INSERT INTO orders (customer_id, created_by) VALUES (?, ?)",
        (customer_id, user_id),
    )
    order_id = cur.lastrowid
    for item_id, qty in lines:
        item = conn.execute(
            "SELECT price_paise, gst_percent FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        conn.execute(
            "INSERT INTO order_lines (order_id, item_id, qty_ordered, rate_paise, gst_percent) "
            "VALUES (?, ?, ?, ?, ?)",
            (order_id, item_id, qty, item["price_paise"], item["gst_percent"]),
        )
    return order_id


def stock_check(conn, order_id):
    """Does finished-goods stock cover this order? Shows the shortage per product."""
    rows = conn.execute(
        "SELECT ol.item_id, i.name, ol.qty_ordered, ol.qty_dispatched "
        "FROM order_lines ol JOIN items i ON i.id = ol.item_id WHERE ol.order_id = ?",
        (order_id,),
    ).fetchall()
    result = []
    for r in rows:
        needed = r["qty_ordered"] - r["qty_dispatched"]
        available = balance(conn, r["item_id"])
        result.append({
            "name": r["name"],
            "needed": needed,
            "available": available,
            "shortage": max(0, needed - available),
        })
    return result


def edit_line_qty(conn, order_line_id, new_qty):
    """Admin can change a quantity before approval."""
    conn.execute("UPDATE order_lines SET qty_ordered = ? WHERE id = ?", (new_qty, order_line_id))


def approve_order(conn, order_id, user_id=None):
    order = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order["status"] != "pending":
        raise ValueError("Only a pending order can be approved")
    conn.execute(
        "UPDATE orders SET status = 'approved', approved_by = ? WHERE id = ?",
        (user_id, order_id),
    )


def reject_order(conn, order_id, user_id=None):
    conn.execute(
        "UPDATE orders SET status = 'rejected', approved_by = ? WHERE id = ?",
        (user_id, order_id),
    )


def invoice_order(conn, order_id):
    """Make the GST invoice for an approved order. Blocked if stock is short."""
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order["status"] != "approved":
        raise ValueError("Order must be approved first")
    if conn.execute("SELECT 1 FROM invoices WHERE order_id = ?", (order_id,)).fetchone():
        raise ValueError("This order already has an invoice")

    short = [c for c in stock_check(conn, order_id) if c["shortage"] > 0]
    if short:
        text = ", ".join(f"{c['name']}: short by {c['shortage']}" for c in short)
        raise ValueError("Not enough stock - " + text)

    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (order["customer_id"],)
    ).fetchone()
    lines = conn.execute("SELECT * FROM order_lines WHERE order_id = ?", (order_id,)).fetchall()

    taxable = cgst = sgst = igst = 0
    for l in lines:
        line_taxable = l["qty_ordered"] * l["rate_paise"]
        c, s, i = calc_tax(line_taxable, l["gst_percent"], customer["state"])
        taxable += line_taxable
        cgst += c
        sgst += s
        igst += i

    today = date.today().isoformat()
    invoice_no = next_invoice_no(conn, today)
    cur = conn.execute(
        "INSERT INTO invoices (invoice_no, order_id, customer_id, invoice_date, taxable_paise, "
        "cgst_paise, sgst_paise, igst_paise, total_paise) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (invoice_no, order_id, order["customer_id"], today, taxable,
         cgst, sgst, igst, taxable + cgst + sgst + igst),
    )
    return cur.lastrowid


def dispatch_order(conn, order_id, user_id=None):
    """Dispatch reduces finished-goods stock through the ledger."""
    invoice = conn.execute("SELECT id FROM invoices WHERE order_id = ?", (order_id,)).fetchone()
    if invoice is None:
        raise ValueError("Make the invoice before dispatch")
    lines = conn.execute("SELECT * FROM order_lines WHERE order_id = ?", (order_id,)).fetchall()
    for l in lines:
        qty = l["qty_ordered"] - l["qty_dispatched"]
        if qty > 0:
            add_movement(conn, l["item_id"], -qty, "sale", "invoices", invoice["id"])
            conn.execute(
                "UPDATE order_lines SET qty_dispatched = qty_ordered WHERE id = ?", (l["id"],)
            )
    conn.execute("UPDATE orders SET status = 'dispatched' WHERE id = ?", (order_id,))


def invoice_outstanding(conn, invoice_id):
    inv = conn.execute("SELECT total_paise FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) AS p FROM payments WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()["p"]
    return inv["total_paise"] - paid


def record_payment(conn, invoice_id, amount_paise, mode="Cash", note=None):
    if amount_paise <= 0:
        raise ValueError("Payment must be more than zero")
    if amount_paise > invoice_outstanding(conn, invoice_id):
        raise ValueError("Payment is more than the outstanding amount")
    cur = conn.execute(
        "INSERT INTO payments (invoice_id, amount_paise, mode, note) VALUES (?, ?, ?, ?)",
        (invoice_id, amount_paise, mode, note),
    )
    return cur.lastrowid


def cancel_invoice(conn, order_id, reason, user_id=None):
    """Cancel a posted invoice with a credit note. The invoice is never deleted."""
    from services.gst import financial_year

    inv = conn.execute("SELECT * FROM invoices WHERE order_id = ?", (order_id,)).fetchone()
    if inv is None:
        raise ValueError("This order has no invoice")
    if conn.execute("SELECT 1 FROM credit_notes WHERE invoice_id = ?", (inv["id"],)).fetchone():
        raise ValueError("This invoice is already cancelled")
    if conn.execute("SELECT 1 FROM payments WHERE invoice_id = ?", (inv["id"],)).fetchone():
        raise ValueError("Payments exist for this invoice. Refund them before cancelling")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Enter a reason for the credit note")

    today = date.today().isoformat()
    prefix = f"CN/{financial_year(today)}/"
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM credit_notes WHERE credit_no LIKE ?", (prefix + "%",)
    ).fetchone()["c"]
    cur = conn.execute(
        "INSERT INTO credit_notes (credit_no, invoice_id, note_date, reason, taxable_paise, "
        "cgst_paise, sgst_paise, igst_paise, total_paise, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (f"{prefix}{count + 1:04d}", inv["id"], today, reason, inv["taxable_paise"],
         inv["cgst_paise"], inv["sgst_paise"], inv["igst_paise"], inv["total_paise"], user_id),
    )
    cn_id = cur.lastrowid

    order = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order["status"] == "dispatched":
        lines = conn.execute(
            "SELECT id, item_id, qty_dispatched FROM order_lines WHERE order_id = ?", (order_id,)
        ).fetchall()
        for l in lines:
            if l["qty_dispatched"] > 0:
                # stock comes back through the ledger, linked to the credit note
                add_movement(conn, l["item_id"], l["qty_dispatched"], "sale",
                             "credit_notes", cn_id, "Stock returned: credit note")
                conn.execute("UPDATE order_lines SET qty_dispatched = 0 WHERE id = ?", (l["id"],))
    conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    return cn_id
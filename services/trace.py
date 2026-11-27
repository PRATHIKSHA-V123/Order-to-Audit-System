def money(paise):
    return f"Rs {paise / 100:,.2f}"


def find_order_id(conn, text):
    """Accepts an invoice number, a credit note number or an order number."""
    text = text.strip().lstrip("#")
    if not text:
        return None
    row = conn.execute(
        "SELECT order_id FROM invoices WHERE upper(invoice_no) = upper(?)", (text,)).fetchone()
    if row:
        return row["order_id"]
    row = conn.execute(
        "SELECT i.order_id FROM credit_notes c JOIN invoices i ON i.id = c.invoice_id "
        "WHERE upper(c.credit_no) = upper(?)", (text,)).fetchone()
    if row:
        return row["order_id"]
    if text.isdigit():
        row = conn.execute("SELECT id FROM orders WHERE id = ?", (int(text),)).fetchone()
        if row:
            return row["id"]
    return None


KIND_BY_ACTION = {
    "QTY_CHANGED": "qty", "PRICE_CHANGED": "qty", "APPROVED": "good", "REJECTED": "bad",
    "INVOICE_CREATED": "invoice", "DISPATCHED": "ship",
    "PAYMENT_RECORDED": "good", "INVOICE_CANCELLED": "bad",
}


def build_trace(conn, order_id):
    """Everything that happened to one order: records, stock movements and audit entries."""
    order = conn.execute(
        "SELECT o.*, c.name AS customer, c.state AS state, u.full_name AS salesman "
        "FROM orders o JOIN customers c ON c.id = o.customer_id "
        "LEFT JOIN users u ON u.id = o.created_by WHERE o.id = ?", (order_id,)).fetchone()
    if order is None:
        return None

    lines = conn.execute(
        "SELECT ol.*, i.name FROM order_lines ol JOIN items i ON i.id = ol.item_id "
        "WHERE ol.order_id = ? ORDER BY ol.id", (order_id,)).fetchall()
    line_names = {l["id"]: l["name"] for l in lines}

    invoice = conn.execute("SELECT * FROM invoices WHERE order_id = ?", (order_id,)).fetchone()
    payments, credit_note, ledger = [], None, []
    if invoice:
        payments = conn.execute(
            "SELECT * FROM payments WHERE invoice_id = ? ORDER BY id", (invoice["id"],)).fetchall()
        credit_note = conn.execute(
            "SELECT * FROM credit_notes WHERE invoice_id = ?", (invoice["id"],)).fetchone()
        sql = ("SELECT l.*, i.name, i.unit FROM stock_ledger l JOIN items i ON i.id = l.item_id "
               "WHERE l.ref_table = ? AND l.ref_id = ? ORDER BY l.id")
        ledger = list(conn.execute(sql, ("invoices", invoice["id"])).fetchall())
        if credit_note:
            ledger += list(conn.execute(sql, ("credit_notes", credit_note["id"])).fetchall())
    pay_by_id = {p["id"]: p for p in payments}

    # every audit entry that belongs to this order
    pairs = [("orders", [order_id]), ("order_lines", list(line_names))]
    if invoice:
        pairs.append(("invoices", [invoice["id"]]))
    if payments:
        pairs.append(("payments", list(pay_by_id)))
    if credit_note:
        pairs.append(("credit_notes", [credit_note["id"]]))
    where, params = [], []
    for table, ids in pairs:
        if ids:
            where.append(f"(a.table_name = ? AND a.record_id IN ({','.join('?' * len(ids))}))")
            params.append(table)
            params.extend(ids)
    audit_rows = conn.execute(
        "SELECT a.*, u.full_name FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
        "WHERE " + " OR ".join(where) + " ORDER BY a.created_at, a.id", params).fetchall()

    def describe(a):
        act = a["action"]
        if act == "QTY_CHANGED":
            name = line_names.get(a["record_id"], "Line")
            return "Quantity changed", f"{name}: {a['old_value']} to {a['new_value']}"
        if act == "PRICE_CHANGED":
            name = line_names.get(a["record_id"], "Line")
            return "Price changed", f"{name}: {money(int(a['old_value']))} to {money(int(a['new_value']))}"
        if act == "APPROVED":
            return "Order approved", "Status changed from pending to approved"
        if act == "REJECTED":
            return "Order rejected", "Status changed from pending to rejected"
        if act == "INVOICE_CREATED" and invoice:
            return "GST invoice created", f"Invoice {invoice['invoice_no']} for {money(invoice['total_paise'])}"
        if act == "DISPATCHED":
            return "Dispatched", "Finished goods stock reduced through the stock ledger"
        if act == "PAYMENT_RECORDED":
            p = pay_by_id.get(a["record_id"])
            return "Payment recorded", (f"{money(p['amount_paise'])} by {p['mode']}" if p else a["new_value"])
        if act == "INVOICE_CANCELLED" and credit_note:
            return "Invoice cancelled", f"Credit note {credit_note['credit_no']}. Reason: {credit_note['reason']}"
        return act, f"{a['old_value'] or ''} {a['new_value'] or ''}".strip()

    events = [{
        "when": order["order_date"] + " 00:00:00", "kind": "order", "title": "Order placed",
        "text": f"{order['customer']} ({order['state']}), {len(lines)} product line(s)",
        "who": order["salesman"] or "-",
    }]
    covered = set()
    for a in audit_rows:
        covered.add((a["table_name"], a["record_id"], a["action"]))
        title, text = describe(a)
        events.append({"when": a["created_at"], "kind": KIND_BY_ACTION.get(a["action"], "order"),
                       "title": title, "text": text, "who": a["full_name"] or "-"})

    # records that have no audit entry (for example, created by a test script) still show up
    if invoice and ("invoices", invoice["id"], "INVOICE_CREATED") not in covered:
        events.append({"when": invoice["invoice_date"] + " 00:00:00", "kind": "invoice",
                       "title": "GST invoice created", "who": "-",
                       "text": f"Invoice {invoice['invoice_no']} for {money(invoice['total_paise'])}"})
    for p in payments:
        if ("payments", p["id"], "PAYMENT_RECORDED") not in covered:
            events.append({"when": p["pay_date"] + " 00:00:00", "kind": "good",
                           "title": "Payment recorded", "who": "-",
                           "text": f"{money(p['amount_paise'])} by {p['mode']}"})
    if credit_note and ("credit_notes", credit_note["id"], "INVOICE_CANCELLED") not in covered:
        events.append({"when": credit_note["note_date"] + " 00:00:00", "kind": "bad",
                       "title": "Invoice cancelled", "who": "-",
                       "text": f"Credit note {credit_note['credit_no']}. Reason: {credit_note['reason']}"})
    events.sort(key=lambda e: e["when"])

    value = sum(l["qty_ordered"] * l["rate_paise"] for l in lines)
    paid = sum(p["amount_paise"] for p in payments)
    outstanding = 0
    if invoice and credit_note is None:
        outstanding = invoice["total_paise"] - paid
    return {
        "order": order, "lines": lines, "invoice": invoice, "payments": payments,
        "credit_note": credit_note, "ledger": ledger, "events": events,
        "value_paise": value, "paid_paise": paid, "outstanding_paise": outstanding,
    }
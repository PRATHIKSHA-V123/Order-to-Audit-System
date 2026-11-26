from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_connection
from routes.auth import role_required
from services.stock import balance
from services import orders as svc
from services.audit import log
from services.trace import build_trace, find_order_id

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def back(order_id):
    return redirect(url_for("admin.order_detail", order_id=order_id))


def run_action(order_id, action, ok_message):
    """Run one admin action. If the rules say no, show the reason and change nothing."""
    conn = get_connection()
    try:
        action(conn)
        conn.commit()
        flash(ok_message)
    except ValueError as e:
        conn.rollback()
        flash(str(e), "error")
    finally:
        conn.close()
    return back(order_id)


@admin_bp.route("/orders")
@role_required("admin")
def orders():
    conn = get_connection()
    rows = conn.execute(
        "SELECT o.id, o.order_date, o.status, c.name AS customer, u.full_name AS salesman, "
        "COALESCE(SUM(ol.qty_ordered * ol.rate_paise), 0) AS value_paise, "
        "EXISTS(SELECT 1 FROM invoices i WHERE i.order_id = o.id) AS has_invoice "
        "FROM orders o JOIN customers c ON c.id = o.customer_id "
        "LEFT JOIN users u ON u.id = o.created_by "
        "LEFT JOIN order_lines ol ON ol.order_id = o.id "
        "GROUP BY o.id ORDER BY o.id DESC"
    ).fetchall()
    conn.close()
    return render_template("admin/orders.html", orders=rows)


@admin_bp.route("/orders/<int:order_id>")
@role_required("admin")
def order_detail(order_id):
    conn = get_connection()
    order = conn.execute(
        "SELECT o.*, c.name AS customer, c.state AS state FROM orders o "
        "JOIN customers c ON c.id = o.customer_id WHERE o.id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        conn.close()
        return "Order not found", 404

    rows = conn.execute(
        "SELECT ol.*, i.name FROM order_lines ol JOIN items i ON i.id = ol.item_id "
        "WHERE ol.order_id = ?",
        (order_id,),
    ).fetchall()
    lines = []
    total_paise = 0
    for r in rows:
        needed = r["qty_ordered"] - r["qty_dispatched"]
        available = balance(conn, r["item_id"])
        total_paise += r["qty_ordered"] * r["rate_paise"]
        lines.append({
            "id": r["id"], "name": r["name"], "rate_paise": r["rate_paise"],
            "qty_ordered": r["qty_ordered"], "available": available,
            "shortage": max(0, needed - available),
        })
    has_shortage = any(l["shortage"] > 0 for l in lines)

    invoice = conn.execute("SELECT * FROM invoices WHERE order_id = ?", (order_id,)).fetchone()
    payments = []
    credit_note = None
    outstanding = 0
    if invoice:
        payments = conn.execute(
            "SELECT * FROM payments WHERE invoice_id = ? ORDER BY id", (invoice["id"],)
        ).fetchall()
        credit_note = conn.execute(
            "SELECT * FROM credit_notes WHERE invoice_id = ?", (invoice["id"],)
        ).fetchone()
        if credit_note is None:
            outstanding = svc.invoice_outstanding(conn, invoice["id"])
    conn.close()

    return render_template(
        "admin/order_detail.html", order=order, lines=lines, total_paise=total_paise,
        has_shortage=has_shortage, invoice=invoice, payments=payments,
        outstanding=outstanding, credit_note=credit_note,
    )


@admin_bp.route("/orders/<int:order_id>/qty", methods=["POST"])
@role_required("admin")
def update_qty(order_id):
    def act(conn):
        status = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()["status"]
        if status != "pending":
            raise ValueError("Only a pending order can be edited")
        for key, value in request.form.items():
            if key.startswith("qty_") and value.strip():
                qty = int(value)
                if qty > 0:
                    line_id = int(key[4:])
                    old = conn.execute(
                        "SELECT qty_ordered FROM order_lines WHERE id = ?", (line_id,)
                    ).fetchone()["qty_ordered"]
                    if old != qty:
                        svc.edit_line_qty(conn, line_id, qty)
                        log(conn, "order_lines", line_id, "QTY_CHANGED", old, qty, session["user_id"])
    return run_action(order_id, act, "Quantities saved")


@admin_bp.route("/orders/<int:order_id>/approve", methods=["POST"])
@role_required("admin")
def approve(order_id):
    def act(conn):
        svc.approve_order(conn, order_id, session["user_id"])
        log(conn, "orders", order_id, "APPROVED", "pending", "approved", session["user_id"])
    return run_action(order_id, act, "Order approved")


@admin_bp.route("/orders/<int:order_id>/reject", methods=["POST"])
@role_required("admin")
def reject(order_id):
    def act(conn):
        old = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()["status"]
        if old != "pending":
            raise ValueError("Only a pending order can be rejected")
        svc.reject_order(conn, order_id, session["user_id"])
        log(conn, "orders", order_id, "REJECTED", old, "rejected", session["user_id"])
    return run_action(order_id, act, "Order rejected")


@admin_bp.route("/orders/<int:order_id>/invoice", methods=["POST"])
@role_required("admin")
def invoice(order_id):
    def act(conn):
        inv_id = svc.invoice_order(conn, order_id)
        no = conn.execute("SELECT invoice_no FROM invoices WHERE id = ?", (inv_id,)).fetchone()["invoice_no"]
        log(conn, "invoices", inv_id, "INVOICE_CREATED", None, no, session["user_id"])
    return run_action(order_id, act, "GST invoice created")


@admin_bp.route("/orders/<int:order_id>/dispatch", methods=["POST"])
@role_required("admin")
def dispatch(order_id):
    def act(conn):
        svc.dispatch_order(conn, order_id, session["user_id"])
        log(conn, "orders", order_id, "DISPATCHED", "approved", "dispatched", session["user_id"])
    return run_action(order_id, act, "Dispatch recorded, stock reduced")


@admin_bp.route("/orders/<int:order_id>/payment", methods=["POST"])
@role_required("admin")
def payment(order_id):
    try:
        paise = int((Decimal(request.form["amount"]) * 100).to_integral_value())
    except (InvalidOperation, KeyError):
        flash("Enter a valid amount", "error")
        return back(order_id)

    def act(conn):
        inv = conn.execute("SELECT id FROM invoices WHERE order_id = ?", (order_id,)).fetchone()
        if inv is None:
            raise ValueError("There is no invoice for this order yet")
        if conn.execute("SELECT 1 FROM credit_notes WHERE invoice_id = ?", (inv["id"],)).fetchone():
            raise ValueError("This invoice is cancelled")
        pay_id = svc.record_payment(conn, inv["id"], paise, request.form.get("mode", "Cash"))
        log(conn, "payments", pay_id, "PAYMENT_RECORDED", None, f"{paise} paise", session["user_id"])
    return run_action(order_id, act, "Payment recorded")


@admin_bp.route("/orders/<int:order_id>/cancel-invoice", methods=["POST"])
@role_required("admin")
def cancel_invoice(order_id):
    def act(conn):
        cn_id = svc.cancel_invoice(conn, order_id, request.form.get("reason"), session["user_id"])
        log(conn, "credit_notes", cn_id, "INVOICE_CANCELLED", "posted", "cancelled", session["user_id"])
    return run_action(order_id, act, "Invoice cancelled with a credit note")


@admin_bp.route("/audit")
@role_required("admin", "accountant", "owner")
def audit():
    conn = get_connection()
    rows = conn.execute(
        "SELECT a.*, u.full_name FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
        "ORDER BY a.id DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return render_template("admin/audit.html", rows=rows)
@admin_bp.route("/trace")
@role_required("admin", "accountant", "owner")
def trace():
    q = request.args.get("q", "").strip()
    order_id = request.args.get("order_id", type=int)
    conn = get_connection()
    if order_id is None and q:
        order_id = find_order_id(conn, q)
    data = build_trace(conn, order_id) if order_id else None
    recent = conn.execute(
        "SELECT o.id, o.status, c.name AS customer, "
        "(SELECT invoice_no FROM invoices i WHERE i.order_id = o.id) AS invoice_no "
        "FROM orders o JOIN customers c ON c.id = o.customer_id ORDER BY o.id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    searched = bool(q) or request.args.get("order_id") is not None
    return render_template("admin/trace.html", q=q, data=data, recent=recent, searched=searched)
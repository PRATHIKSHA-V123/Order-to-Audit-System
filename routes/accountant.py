import csv
import io
from datetime import date
from decimal import Decimal
from flask import Blueprint, render_template, request, Response
from database.db import get_connection
from routes.auth import role_required
from services.stock import all_balances
from services.pdf_invoice import build_invoice_pdf

accountant_bp = Blueprint("reports", __name__, url_prefix="/reports")
ROLES = ("accountant", "admin", "owner")
UNIT = {"g": ("kg", 1000), "ml": ("L", 1000), "pc": ("pieces", 1)}

# Cancelled invoices (with a credit note) are left out of the reports
NOT_CANCELLED = " AND NOT EXISTS (SELECT 1 FROM credit_notes cn WHERE cn.invoice_id = inv.id)"


def money(paise):
    return f"{Decimal(paise) / 100:.2f}"


def date_filter(column, d_from, d_to):
    sql, params = "", []
    if d_from:
        sql += f" AND {column} >= ?"
        params.append(d_from)
    if d_to:
        sql += f" AND {column} <= ?"
        params.append(d_to)
    return sql, params


def csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def sales_rows(conn, d_from, d_to):
    where, params = date_filter("inv.invoice_date", d_from, d_to)
    return conn.execute(
        "SELECT inv.id, inv.invoice_no, inv.invoice_date, c.name AS customer, c.gstin, c.state, "
        "inv.taxable_paise, inv.cgst_paise, inv.sgst_paise, inv.igst_paise, inv.total_paise "
        "FROM invoices inv JOIN customers c ON c.id = inv.customer_id WHERE 1=1"
        + NOT_CANCELLED + where + " ORDER BY inv.id", params).fetchall()


def gst_rows(conn, d_from, d_to):
    where, params = date_filter("inv.invoice_date", d_from, d_to)
    return conn.execute(
        "SELECT c.state, COUNT(*) AS invoices, SUM(inv.taxable_paise) AS taxable_paise, "
        "SUM(inv.cgst_paise) AS cgst_paise, SUM(inv.sgst_paise) AS sgst_paise, "
        "SUM(inv.igst_paise) AS igst_paise, SUM(inv.total_paise) AS total_paise "
        "FROM invoices inv JOIN customers c ON c.id = inv.customer_id WHERE 1=1"
        + NOT_CANCELLED + where + " GROUP BY c.state ORDER BY c.state", params).fetchall()


def outstanding_rows(conn):
    rows = conn.execute(
        "SELECT inv.id, inv.invoice_no, inv.invoice_date, c.name AS customer, inv.total_paise, "
        "COALESCE((SELECT SUM(p.amount_paise) FROM payments p WHERE p.invoice_id = inv.id), 0) "
        "AS paid_paise FROM invoices inv JOIN customers c ON c.id = inv.customer_id "
        "WHERE 1=1" + NOT_CANCELLED + " ORDER BY c.name, inv.id").fetchall()
    today = date.today()
    result = []
    for r in rows:
        due = r["total_paise"] - r["paid_paise"]
        if due <= 0:
            continue
        age = (today - date.fromisoformat(r["invoice_date"])).days
        result.append({
            "customer": r["customer"], "invoice_no": r["invoice_no"],
            "invoice_date": r["invoice_date"], "total": r["total_paise"],
            "paid": r["paid_paise"], "due": due, "age": age,
            "b1": due if age <= 30 else 0,
            "b2": due if 31 <= age <= 60 else 0,
            "b3": due if age > 60 else 0,
        })
    return result


@accountant_bp.route("/sales")
@role_required(*ROLES)
def sales():
    d_from = request.args.get("date_from", "")
    d_to = request.args.get("date_to", "")
    conn = get_connection()
    rows = sales_rows(conn, d_from, d_to)
    where, params = date_filter("inv.invoice_date", d_from, d_to)
    products = conn.execute(
        "SELECT i.name, SUM(ol.qty_ordered) AS qty, "
        "SUM(ol.qty_ordered * ol.rate_paise) AS taxable_paise "
        "FROM invoices inv JOIN order_lines ol ON ol.order_id = inv.order_id "
        "JOIN items i ON i.id = ol.item_id WHERE 1=1" + NOT_CANCELLED + where +
        " GROUP BY i.id ORDER BY taxable_paise DESC", params).fetchall()
    conn.close()

    customers = {}
    for r in rows:
        c = customers.setdefault(r["customer"], {"invoices": 0, "taxable": 0, "total": 0})
        c["invoices"] += 1
        c["taxable"] += r["taxable_paise"]
        c["total"] += r["total_paise"]
    totals = {k: sum(r[k] for r in rows) for k in
              ("taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_paise")}
    return render_template("accountant/sales.html", rows=rows, products=products,
                           customers=customers, totals=totals,
                           date_from=d_from, date_to=d_to)


@accountant_bp.route("/sales.csv")
@role_required(*ROLES)
def sales_csv():
    conn = get_connection()
    rows = sales_rows(conn, request.args.get("date_from", ""), request.args.get("date_to", ""))
    conn.close()
    header = ["Invoice no", "Date", "Customer", "GSTIN", "Place of supply",
              "Taxable", "CGST", "SGST", "IGST", "Total"]
    data = [[r["invoice_no"], r["invoice_date"], r["customer"], r["gstin"] or "", r["state"],
             money(r["taxable_paise"]), money(r["cgst_paise"]), money(r["sgst_paise"]),
             money(r["igst_paise"]), money(r["total_paise"])] for r in rows]
    return csv_response("sales_register.csv", header, data)


@accountant_bp.route("/gst")
@role_required(*ROLES)
def gst():
    d_from = request.args.get("date_from", "")
    d_to = request.args.get("date_to", "")
    conn = get_connection()
    rows = gst_rows(conn, d_from, d_to)
    conn.close()
    totals = {k: sum(r[k] for r in rows) for k in
              ("invoices", "taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_paise")}
    return render_template("accountant/gst.html", rows=rows, totals=totals,
                           date_from=d_from, date_to=d_to)


@accountant_bp.route("/gst.csv")
@role_required(*ROLES)
def gst_csv():
    conn = get_connection()
    rows = gst_rows(conn, request.args.get("date_from", ""), request.args.get("date_to", ""))
    conn.close()
    header = ["Place of supply", "Invoices", "Taxable", "CGST", "SGST", "IGST", "Invoice value"]
    data = [[r["state"], r["invoices"], money(r["taxable_paise"]), money(r["cgst_paise"]),
             money(r["sgst_paise"]), money(r["igst_paise"]), money(r["total_paise"])] for r in rows]
    return csv_response("gst_summary.csv", header, data)


@accountant_bp.route("/outstanding")
@role_required(*ROLES)
def outstanding():
    conn = get_connection()
    rows = outstanding_rows(conn)
    conn.close()
    totals = {k: sum(r[k] for r in rows) for k in ("total", "paid", "due", "b1", "b2", "b3")}
    return render_template("accountant/outstanding.html", rows=rows, totals=totals)


@accountant_bp.route("/outstanding.csv")
@role_required(*ROLES)
def outstanding_csv():
    conn = get_connection()
    rows = outstanding_rows(conn)
    conn.close()
    header = ["Customer", "Invoice", "Date", "Total", "Paid", "Outstanding",
              "Age (days)", "0-30 days", "31-60 days", "Over 60 days"]
    data = [[r["customer"], r["invoice_no"], r["invoice_date"], money(r["total"]),
             money(r["paid"]), money(r["due"]), r["age"],
             money(r["b1"]), money(r["b2"]), money(r["b3"])] for r in rows]
    return csv_response("outstanding.csv", header, data)


@accountant_bp.route("/stock.csv")
@role_required(*ROLES)
def stock_csv():
    data = []
    for r in all_balances():
        unit_name, factor = UNIT[r["unit"]]
        data.append([r["name"], r["item_type"], format(Decimal(r["bal"]) / factor, "f"), unit_name])
    return csv_response("stock_summary.csv", ["Item", "Type", "Balance", "Unit"], data)


@accountant_bp.route("/invoice/<int:invoice_id>.pdf")
@role_required(*ROLES)
def invoice_pdf(invoice_id):
    conn = get_connection()
    data = build_invoice_pdf(conn, invoice_id)
    conn.close()
    if data is None:
        return "Invoice not found", 404
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=invoice-{invoice_id}.pdf"})
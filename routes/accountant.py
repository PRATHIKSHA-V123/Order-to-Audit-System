import csv
import io
import zipfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, render_template, request, Response, abort
from database.db import get_connection
from routes.auth import role_required
from services.stock import all_balances
from services.pdf_invoice import build_invoice_pdf
from services.report_pdf import table_pdf
from services.production import variance_pct, is_flagged
from services.costing import run_cost

accountant_bp = Blueprint("reports", __name__, url_prefix="/reports")
ROLES = ("accountant", "admin", "owner")
UNIT = {"g": ("kg", 1000), "ml": ("L", 1000), "pc": ("pieces", 1)}

# Cancelled invoices (with a credit note) are left out of the reports
NOT_CANCELLED = " AND NOT EXISTS (SELECT 1 FROM credit_notes cn WHERE cn.invoice_id = inv.id)"


def money(paise):
    return f"{Decimal(paise) / 100:.2f}"


def dq(unit, qty):
    """Base units (g, ml, pc) -> kg, L or pieces, as plain text."""
    factor = UNIT[unit][1]
    return format((Decimal(qty) / factor).normalize(), "f")


def date_filter(column, d_from, d_to):
    sql, params = "", []
    if d_from:
        sql += f" AND {column} >= ?"
        params.append(d_from)
    if d_to:
        sql += f" AND {column} <= ?"
        params.append(d_to)
    return sql, params


def period_text(d_from, d_to):
    if d_from and d_to:
        return f"Period: {d_from} to {d_to}"
    if d_from:
        return f"Period: from {d_from}"
    if d_to:
        return f"Period: up to {d_to}"
    return "Period: all dates"


def csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------------------------------------------------------------- queries
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


# ---------------------------------------------------------------- report builders
# Each builder returns one table: title, headers, rows, PDF column weights, file name.
def build_sales(conn, d_from, d_to):
    rows = sales_rows(conn, d_from, d_to)
    data = [[r["invoice_no"], r["invoice_date"], r["customer"], r["gstin"] or "", r["state"],
             money(r["taxable_paise"]), money(r["cgst_paise"]), money(r["sgst_paise"]),
             money(r["igst_paise"]), money(r["total_paise"])] for r in rows]
    if rows:
        keys = ("taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_paise")
        data.append(["TOTAL", "", "", "", ""] + [money(sum(r[k] for r in rows)) for k in keys])
    return {"title": "Sales Register", "file": "sales_register",
            "headers": ["Invoice", "Date", "Customer", "GSTIN", "Place of supply",
                        "Taxable", "CGST", "SGST", "IGST", "Total"],
            "rows": data, "weights": [2.2, 1.3, 2, 2.5, 1.9, 1.4, 1.2, 1.2, 1.2, 1.5]}


def build_gst(conn, d_from, d_to):
    rows = gst_rows(conn, d_from, d_to)
    data = [[r["state"], r["invoices"], money(r["taxable_paise"]), money(r["cgst_paise"]),
             money(r["sgst_paise"]), money(r["igst_paise"]), money(r["total_paise"])]
            for r in rows]
    if rows:
        keys = ("taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_paise")
        data.append(["TOTAL", sum(r["invoices"] for r in rows)]
                    + [money(sum(r[k] for r in rows)) for k in keys])
    return {"title": "GST Summary of Outward Supplies", "file": "gst_summary",
            "headers": ["Place of supply", "Invoices", "Taxable", "CGST", "SGST", "IGST",
                        "Invoice value"],
            "rows": data, "weights": [2.5, 1, 1.6, 1.3, 1.3, 1.3, 1.6]}


def build_purchases(conn, d_from, d_to):
    where, params = date_filter("p.purchase_date", d_from, d_to)
    rows = conn.execute(
        "SELECT p.purchase_date, p.qty, p.total_paise, p.supplier, i.name, i.unit "
        "FROM purchases p JOIN items i ON i.id = p.item_id "
        "WHERE COALESCE(p.supplier, '') != 'OPENING STOCK'" + where + " ORDER BY p.id",
        params).fetchall()
    data = []
    for r in rows:
        units = Decimal(r["qty"]) / UNIT[r["unit"]][1]
        rate = (Decimal(r["total_paise"]) / 100 / units).quantize(
            Decimal("0.01"), ROUND_HALF_UP) if units else Decimal("0.00")
        data.append([r["purchase_date"], r["name"], dq(r["unit"], r["qty"]), UNIT[r["unit"]][0],
                     str(rate), money(r["total_paise"]), r["supplier"] or ""])
    if rows:
        data.append(["TOTAL", "", "", "", "", money(sum(r["total_paise"] for r in rows)), ""])
    return {"title": "Purchase Register", "file": "purchase_register",
            "headers": ["Date", "Item", "Quantity", "Unit", "Rate (Rs/unit)", "Total (Rs)",
                        "Supplier"],
            "rows": data, "weights": [1.4, 2.4, 1.2, 1, 1.6, 1.4, 2.2]}


def build_stock(conn, d_from, d_to):
    data = [[r["name"], r["item_type"], dq(r["unit"], r["bal"]), UNIT[r["unit"]][0]]
            for r in all_balances()]
    return {"title": "Stock Summary (as of today)", "file": "stock_summary",
            "headers": ["Item", "Type", "Balance", "Unit"],
            "rows": data, "weights": [3, 1.5, 1.5, 1]}


def build_ledger(conn, d_from, d_to):
    where, params = date_filter("l.txn_date", d_from, d_to)
    rows = conn.execute(
        "SELECT l.*, i.name, i.unit FROM stock_ledger l JOIN items i ON i.id = l.item_id "
        "WHERE 1=1" + where + " ORDER BY l.id", params).fetchall()
    data = [[r["txn_date"], r["name"], r["txn_type"], dq(r["unit"], r["qty_change"]),
             UNIT[r["unit"]][0],
             f"{r['ref_table']} #{r['ref_id']}" if r["ref_table"] else "",
             r["note"] or ""] for r in rows]
    return {"title": "Stock Ledger", "file": "stock_ledger",
            "headers": ["Date", "Item", "Type", "Change", "Unit", "Source", "Note"],
            "rows": data, "weights": [1.3, 2.2, 2, 1.2, 0.9, 2, 2.4]}


def build_production(conn, d_from, d_to):
    where, params = date_filter("r.run_date", d_from, d_to)
    runs = conn.execute(
        "SELECT r.id, r.run_date, r.planned_output, r.actual_output, i.name "
        "FROM production_runs r JOIN items i ON i.id = r.product_id WHERE 1=1"
        + where + " ORDER BY r.id", params).fetchall()
    data = []
    for r in runs:
        pct = variance_pct(r["planned_output"], r["actual_output"])
        try:
            c = run_cost(conn, r["id"])
            costs = [money(c["material"]), money(c["labour"]), money(c["overhead"]),
                     money(c["per_packet"])]
        except ArithmeticError:
            costs = ["-", "-", "-", "-"]
        data.append([f"#{r['id']}", r["run_date"], r["name"], r["planned_output"],
                     r["actual_output"], str(pct), "FLAG" if is_flagged(pct) else ""] + costs)
    return {"title": "Production Report (amounts in Rs)", "file": "production_report",
            "headers": ["Run", "Date", "Product", "Expected", "Actual", "Yield var %", "Flag",
                        "Materials", "Labour", "Overheads", "Cost/packet"],
            "rows": data, "weights": [0.8, 1.3, 2, 1.1, 1.1, 1.6, 0.9, 1.5, 1.3, 1.4, 1.7]}


def build_variance(conn, d_from, d_to):
    where, params = date_filter("r.run_date", d_from, d_to)
    mats = conn.execute(
        "SELECT i.id, i.name, i.unit, SUM(pl.planned_qty) AS planned, SUM(pl.actual_qty) AS actual "
        "FROM production_lines pl JOIN production_runs r ON r.id = pl.run_id "
        "JOIN items i ON i.id = pl.item_id WHERE 1=1" + where + " GROUP BY i.id ORDER BY i.id",
        params).fetchall()
    bad = {row["item_id"]: row["bad"] for row in conn.execute(
        "SELECT l.item_id, SUM(-l.qty_change) AS bad FROM stock_ledger l "
        "JOIN production_runs r ON r.id = l.ref_id "
        "WHERE l.txn_type = 'damage' AND l.ref_table = 'production_runs'" + where +
        " GROUP BY l.item_id", params)}
    data = []
    for m in mats:
        pct = variance_pct(m["planned"], m["actual"])
        data.append([m["name"], UNIT[m["unit"]][0], dq(m["unit"], m["planned"]),
                     dq(m["unit"], m["actual"]), str(pct), "FLAG" if is_flagged(pct) else "",
                     dq(m["unit"], bad.get(m["id"], 0))])
    return {"title": "Material Variance and Wastage (planned vs actual)", "file": "material_variance",
            "headers": ["Material", "Unit", "Planned", "Actual", "Variance %", "Flag", "Wastage"],
            "rows": data, "weights": [2.5, 0.8, 1.4, 1.4, 1.4, 0.9, 1.4]}


def build_collections(conn, d_from, d_to):
    where, params = date_filter("p.pay_date", d_from, d_to)
    rows = conn.execute(
        "SELECT p.pay_date, p.amount_paise, p.mode, inv.invoice_no, c.name AS customer "
        "FROM payments p JOIN invoices inv ON inv.id = p.invoice_id "
        "JOIN customers c ON c.id = inv.customer_id WHERE 1=1"
        + NOT_CANCELLED + where + " ORDER BY p.id", params).fetchall()
    data = [[r["pay_date"], r["invoice_no"], r["customer"], r["mode"] or "",
             money(r["amount_paise"])] for r in rows]
    if rows:
        data.append(["TOTAL", "", "", "", money(sum(r["amount_paise"] for r in rows))])
    return {"title": "Payments and Collections", "file": "collections",
            "headers": ["Date", "Invoice", "Customer", "Mode", "Amount (Rs)"],
            "rows": data, "weights": [1.5, 2.4, 2.4, 1.4, 1.5]}


def build_outstanding(conn, d_from, d_to):
    rows = outstanding_rows(conn)
    data = [[r["customer"], r["invoice_no"], r["invoice_date"], money(r["total"]),
             money(r["paid"]), money(r["due"]), r["age"], money(r["b1"]), money(r["b2"]),
             money(r["b3"])] for r in rows]
    if rows:
        keys = ("total", "paid", "due")
        data.append(["TOTAL", "", ""] + [money(sum(r[k] for r in rows)) for k in keys]
                    + [""] + [money(sum(r[k] for r in rows)) for k in ("b1", "b2", "b3")])
    return {"title": "Outstanding Receivables with Ageing (as of today)", "file": "outstanding",
            "headers": ["Customer", "Invoice", "Date", "Total", "Paid", "Outstanding",
                        "Age (days)", "0-30 days", "31-60 days", "Over 60 days"],
            "rows": data, "weights": [1.8, 2.1, 1.4, 1.3, 1.3, 1.5, 1.2, 1.3, 1.3, 1.4]}


BUILDERS = {
    "sales": build_sales, "gst": build_gst, "purchases": build_purchases,
    "stock": build_stock, "ledger": build_ledger, "production": build_production,
    "variance": build_variance, "collections": build_collections,
    "outstanding": build_outstanding,
}


# ---------------------------------------------------------------- pages
@accountant_bp.route("/hub")
@role_required(*ROLES)
def hub():
    return render_template("accountant/reports_hub.html",
                           date_from=request.args.get("date_from", ""),
                           date_to=request.args.get("date_to", ""))


@accountant_bp.route("/view/<name>")
@role_required(*ROLES)
def view(name):
    if name not in BUILDERS:
        abort(404)
    d_from = request.args.get("date_from", "")
    d_to = request.args.get("date_to", "")
    conn = get_connection()
    report = BUILDERS[name](conn, d_from, d_to)
    conn.close()
    return render_template("accountant/report_table.html", report=report, name=name,
                           date_from=d_from, date_to=d_to, period=period_text(d_from, d_to))


@accountant_bp.route("/export/<name>.<fmt>")
@role_required(*ROLES)
def export(name, fmt):
    if name not in BUILDERS or fmt not in ("csv", "pdf"):
        abort(404)
    d_from = request.args.get("date_from", "")
    d_to = request.args.get("date_to", "")
    conn = get_connection()
    report = BUILDERS[name](conn, d_from, d_to)
    conn.close()
    if fmt == "csv":
        return csv_response(report["file"] + ".csv", report["headers"], report["rows"])
    data = table_pdf(report["title"], period_text(d_from, d_to) + "   |   Amounts in Rs",
                     report["headers"], report["rows"], report["weights"])
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={report['file']}.pdf"})


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
@accountant_bp.route("/audit-pack.zip")
@role_required(*ROLES)
def audit_pack():
    """One ZIP for the auditor: every report as a PDF, plus the audit log."""
    d_from = request.args.get("date_from", "")
    d_to = request.args.get("date_to", "")
    period = period_text(d_from, d_to)
    conn = get_connection()
    buf = io.BytesIO()
    names = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        n = 0
        for key, builder in BUILDERS.items():
            n += 1
            report = builder(conn, d_from, d_to)
            pdf = table_pdf(report["title"], period + "   |   Amounts in Rs",
                            report["headers"], report["rows"], report["weights"])
            fname = f"{n:02d}_{report['file']}.pdf"
            z.writestr(fname, pdf)
            names.append(f"{fname}  -  {report['title']}")

        where, params = date_filter("date(a.created_at)", d_from, d_to)
        audit_rows = conn.execute(
            "SELECT a.created_at, u.full_name, a.action, a.table_name, a.record_id, "
            "a.old_value, a.new_value FROM audit_log a "
            "LEFT JOIN users u ON u.id = a.user_id WHERE 1=1" + where + " ORDER BY a.id",
            params).fetchall()
        data = [[r["created_at"], r["full_name"] or "-", r["action"],
                 f"{r['table_name']} #{r['record_id']}", r["old_value"] or "",
                 r["new_value"] or ""] for r in audit_rows]
        n += 1
        fname = f"{n:02d}_audit_log.pdf"
        z.writestr(fname, table_pdf(
            "Audit Log", period + "   |   Times in UTC",
            ["Time (UTC)", "User", "Action", "Record", "Old", "New"], data,
            [2, 1.8, 2.2, 2, 2, 2.4]))
        names.append(f"{fname}  -  Audit Log")

        z.writestr("00_README.txt",
                   "SnackFlow ERP - Audit Pack\n"
                   f"Generated on {date.today().isoformat()}\n"
                   f"{period}\n"
                   "Cancelled invoices (with a credit note) are left out of the sales reports.\n\n"
                   "Contents:\n" + "\n".join(names) + "\n")
    conn.close()
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition":
                             f"attachment; filename=audit_pack_{date.today().isoformat()}.zip"})
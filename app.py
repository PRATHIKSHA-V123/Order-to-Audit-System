from flask import Flask, render_template, redirect, url_for, session
from routes.auth import auth_bp, login_required
from routes.salesman import salesman_bp
from routes.admin import admin_bp
from routes.production import production_bp
from routes.accountant import accountant_bp
from routes.masters import masters_bp
from routes.owner import owner_bp
from services.gst import rupees
from services.stock import format_qty

app = Flask(__name__)
app.secret_key = "change-this-secret-key"   # needed for login sessions
app.register_blueprint(auth_bp)
app.register_blueprint(salesman_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(production_bp)
app.register_blueprint(accountant_bp)
app.register_blueprint(masters_bp)
app.register_blueprint(owner_bp)


def status_label(status, has_invoice=False):
    """Words the salesman sees: submitted, approved, invoiced, dispatched."""
    if status == "pending":
        return "submitted"
    if status == "approved" and has_invoice:
        return "invoiced"
    return status


app.jinja_env.filters["rupees"] = rupees
app.jinja_env.globals["status_label"] = status_label
app.jinja_env.globals["qty_fmt"] = format_qty
app.jinja_env.globals["app_name"] = "SnackFlow ERP"
app.jinja_env.globals["app_tagline"] = "Order-to-Audit Management System for Snack Manufacturing"

# What each role sees on its dashboard: (title, description, page or None)
MENUS = {
    "salesman": [
        ("New Order", "Pick a customer and add products", "salesman.new_order"),
        ("My Orders", "Order status and customer-wise sales", "salesman.my_orders"),
    ],
    "admin": [
        ("Orders", "Approve, invoice, dispatch and record payments", "admin.orders"),
        ("Reports Centre", "All reports with CSV and PDF export", "reports.hub"),
        ("Sales Register", "Invoices and PDF download", "reports.sales"),
        ("Outstanding", "Receivables by customer", "reports.outstanding"),
        ("Stock", "Raw, packing and finished goods", "production.stock"),
        ("Stock Ledger", "Every stock movement", "production.ledger"),
        ("Audit Log", "Who changed what, and when", "admin.audit"),
        ("Order Trace", "Follow one order from start to audit", "admin.trace"),
        ("Audit Pack", "Download all reports as one ZIP for the auditor", "reports.audit_pack"),
        ("Masters", "Products, customers, prices, recipes", "masters.index"),
        ("Business Summary", "Orders, stock, variance, cost and dues at a glance", "owner.summary"),
    ],
    "production": [
        ("Purchases", "Record raw material receipts", "production.purchase"),
        ("Production Run", "Issue material, enter actual output", "production.run"),
        ("Stock", "Raw, packing and finished goods", "production.stock"),
        ("Stock Ledger", "Every stock movement", "production.ledger"),
    ],
    "accountant": [
        ("Reports Centre", "All reports with CSV and PDF export", "reports.hub"),
        ("Sales Register", "Sales, customer-wise and product-wise", "reports.sales"),
        ("GST Summary", "Outward supplies for GSTR-1 / 3B", "reports.gst"),
        ("Outstanding", "Receivables with ageing", "reports.outstanding"),
        ("Stock", "Stock summary", "production.stock"),
        ("Stock Ledger", "Every stock movement", "production.ledger"),
        ("Stock Report (CSV)", "Download for Excel", "reports.stock_csv"),
        ("Audit Log", "Who changed what, and when", "admin.audit"),
        ("Order Trace", "Follow one order from start to audit", "admin.trace"),
        ("Audit Pack", "Download all reports as one ZIP for the auditor", "reports.audit_pack"),
    ],
    "owner": [
        ("Business Summary", "Orders, stock, variance, cost and dues at a glance", "owner.summary"),
        ("Reports Centre", "All reports with CSV and PDF export", "reports.hub"),
        ("Stock Levels", "Current balances", "production.stock"),
        ("Outstanding Dues", "Money to collect", "reports.outstanding"),
        ("Sales Register", "Sales and GST", "reports.sales"),
        ("Audit Log", "Who changed what, and when", "admin.audit"),
        ("Order Trace", "Follow one order from start to audit", "admin.trace"),
        ("Audit Pack", "Download all reports as one ZIP for the auditor", "reports.audit_pack"),
    ],
}


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth.login"))


@app.route("/dashboard")
@login_required
def dashboard():
    menu = MENUS.get(session["role"], [])
    return render_template("dashboard.html", menu=menu)


if __name__ == "__main__":
    app.run(debug=True)
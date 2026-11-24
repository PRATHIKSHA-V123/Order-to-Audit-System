from datetime import date
from flask import Blueprint, render_template
from database.db import get_connection
from routes.auth import role_required
from routes.accountant import outstanding_rows, NOT_CANCELLED
from services.stock import all_balances
from services.production import run_report
from services.costing import run_cost

owner_bp = Blueprint("owner", __name__, url_prefix="/owner")


@owner_bp.route("/summary")
@role_required("owner", "admin")
def summary():
    today = date.today().isoformat()
    conn = get_connection()

    row = conn.execute(
        "SELECT COUNT(DISTINCT o.id) AS c, COALESCE(SUM(ol.qty_ordered * ol.rate_paise), 0) AS v "
        "FROM orders o LEFT JOIN order_lines ol ON ol.order_id = o.id "
        "WHERE o.order_date = ? AND o.status NOT IN ('rejected', 'cancelled')", (today,)
    ).fetchone()
    orders_today, today_value = row["c"], row["v"]

    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM orders WHERE status = 'pending'").fetchone()["c"]
    status_counts = conn.execute(
        "SELECT status, COUNT(*) AS c FROM orders GROUP BY status ORDER BY status").fetchall()

    sales = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(inv.total_paise), 0) AS t FROM invoices inv WHERE 1=1"
        + NOT_CANCELLED).fetchone()

    outstanding_total = sum(r["due"] for r in outstanding_rows(conn))

    latest, report, cost, alerts = None, None, None, []
    latest = conn.execute(
        "SELECT id, run_date FROM production_runs ORDER BY id DESC LIMIT 1").fetchone()
    if latest:
        report = run_report(conn, latest["id"])
        cost = run_cost(conn, latest["id"])
        if report["yield_flag"]:
            alerts.append({
                "what": f"Yield: {report['actual_output']} packets vs {report['planned_output']} expected",
                "pct": report["yield_pct"]})
        for l in report["lines"]:
            if l["flag"]:
                alerts.append({"what": f"{l['name']} consumption", "pct": l["pct"]})
    conn.close()

    rows = all_balances()
    groups = [
        ("Raw materials", [r for r in rows if r["item_type"] == "raw"]),
        ("Packing materials", [r for r in rows if r["item_type"] == "packing"]),
        ("Finished goods", [r for r in rows if r["item_type"] == "finished"]),
    ]
    return render_template(
        "owner/summary.html", today=today, orders_today=orders_today, today_value=today_value,
        pending=pending, status_counts=status_counts, sales_total=sales["t"],
        sales_count=sales["c"], outstanding_total=outstanding_total, groups=groups,
        latest=latest, alerts=alerts, cost=cost)
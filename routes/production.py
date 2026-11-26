from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_connection
from routes.auth import role_required
from services.stock import record_purchase, all_balances
from services.production import get_bom, record_run, run_report
from services.costing import run_cost

production_bp = Blueprint("production", __name__, url_prefix="/production")

# base unit -> (name shown on forms, base units in one shown unit)
BIG = {"g": ("kg", 1000), "ml": ("L", 1000), "pc": ("pieces", 1)}
VIEW_ROLES = ("production", "admin", "accountant", "owner")


def to_base(value, base_unit):
    """Typed kg / L / pieces -> base units (g, ml, pc) as a whole number."""
    return int((Decimal(value) * BIG[base_unit][1]).quantize(Decimal("1"), ROUND_HALF_UP))


def to_paise(rupees_text):
    return int((Decimal(rupees_text) * 100).quantize(Decimal("1"), ROUND_HALF_UP))


@production_bp.route("/purchase", methods=["GET", "POST"])
@role_required("production")
def purchase():
    conn = get_connection()
    items = conn.execute(
        "SELECT id, name, unit FROM items WHERE item_type IN ('raw', 'packing') ORDER BY id"
    ).fetchall()

    if request.method == "POST":
        try:
            item_id = int(request.form["item_id"])
            qty = Decimal(request.form["qty"])
            rate = Decimal(request.form["rate"])
            item = next((i for i in items if i["id"] == item_id), None)
            if item is None or qty <= 0 or rate < 0:
                raise ValueError("Choose an item and enter a quantity and rate")
            total = int((qty * rate * 100).quantize(Decimal("1"), ROUND_HALF_UP))
            record_purchase(conn, item_id, to_base(qty, item["unit"]), total,
                            request.form.get("supplier") or None, session["user_id"])
            conn.commit()
            conn.close()
            flash("Purchase saved. Stock is updated.")
            return redirect(url_for("production.purchase"))
        except (InvalidOperation, ValueError, KeyError) as e:
            conn.rollback()
            flash(str(e) if isinstance(e, ValueError) and "Choose" in str(e)
                  else "Enter valid numbers", "error")

    recent = conn.execute(
        "SELECT p.purchase_date, i.name, i.unit, p.qty, p.total_paise, p.supplier "
        "FROM purchases p JOIN items i ON i.id = p.item_id ORDER BY p.id DESC LIMIT 10"
    ).fetchall()
    suppliers = conn.execute("SELECT name FROM suppliers ORDER BY name").fetchall()
    conn.close()
    unit_names = {k: v[0] for k, v in BIG.items()}
    return render_template("production/purchase.html", items=items, recent=recent,
                           unit_names=unit_names, suppliers=suppliers)


@production_bp.route("/run", methods=["GET", "POST"])
@role_required("production")
def run():
    conn = get_connection()
    product_id = request.values.get("product_id", type=int)
    if product_id is None:
        first = conn.execute("SELECT product_id FROM bom_header ORDER BY id LIMIT 1").fetchone()
        if first is None:
            conn.close()
            return "No product has a BOM yet", 404
        product_id = first["product_id"]
    product = conn.execute("SELECT id, name FROM items WHERE id = ?", (product_id,)).fetchone()
    header, lines = get_bom(conn, product_id)

    if request.method == "POST":
        try:
            batches = int(request.form["batches"])
            actual_output = int(request.form["actual_output"])
            if batches < 1 or actual_output < 0:
                raise ValueError("Batches must be at least 1 and output cannot be negative")
            labour = to_paise(request.form.get("labour") or "0")
            overhead = to_paise(request.form.get("overhead") or "0")
            used, damaged = {}, {}
            for l in lines:
                u = to_base(request.form.get(f"used_{l['item_id']}") or "0", l["unit"])
                d = to_base(request.form.get(f"bad_{l['item_id']}") or "0", l["unit"])
                if d > u:
                    raise ValueError(f"{l['name']}: damaged cannot be more than used")
                used[l["item_id"]] = u
                damaged[l["item_id"]] = d
            run_id = record_run(conn, product_id, batches, used, actual_output,
                                damaged=damaged, labour_paise=labour,
                                overhead_paise=overhead, user_id=session["user_id"])
            conn.commit()
            conn.close()
            flash("Production run saved. Raw stock went down and finished goods went up.")
            return redirect(url_for("production.run_detail", run_id=run_id))
        except InvalidOperation:
            conn.rollback()
            flash("Enter valid numbers", "error")
        except ValueError as e:
            conn.rollback()
            flash(str(e), "error")

    rows = []
    for l in lines:
        name, factor = BIG[l["unit"]]
        rows.append({
            "item_id": l["item_id"], "name": l["name"], "unit_name": name,
            "standard": format(Decimal(l["qty_per_batch"]) / factor, "f"),
        })
    recent = conn.execute(
        "SELECT id, run_date, planned_output, actual_output FROM production_runs "
        "WHERE product_id = ? ORDER BY id DESC LIMIT 10", (product_id,)
    ).fetchall()
    conn.close()
    return render_template("production/run.html", product=product, rows=rows,
                           recent=recent, planned=header["planned_output"])


@production_bp.route("/run/<int:run_id>")
@role_required(*VIEW_ROLES)
def run_detail(run_id):
    conn = get_connection()
    run = conn.execute(
        "SELECT r.*, i.name AS product FROM production_runs r "
        "JOIN items i ON i.id = r.product_id WHERE r.id = ?", (run_id,)
    ).fetchone()
    if run is None:
        conn.close()
        return "Run not found", 404
    report = run_report(conn, run_id)
    units = {r["name"]: r["unit"] for r in conn.execute("SELECT name, unit FROM items")}
    for l in report["lines"]:
        l["unit"] = units[l["name"]]
    cost = run_cost(conn, run_id)
    conn.close()
    return render_template("production/run_report.html", run=run, report=report, cost=cost)


@production_bp.route("/stock")
@role_required(*VIEW_ROLES)
def stock():
    rows = all_balances()
    groups = [
        ("Raw materials", [r for r in rows if r["item_type"] == "raw"]),
        ("Packing materials", [r for r in rows if r["item_type"] == "packing"]),
        ("Finished goods", [r for r in rows if r["item_type"] == "finished"]),
    ]
    return render_template("production/stock.html", groups=groups)


@production_bp.route("/ledger")
@role_required(*VIEW_ROLES)
def ledger():
    item_id = request.args.get("item_id", type=int)
    conn = get_connection()
    sql = ("SELECT l.*, i.name, i.unit FROM stock_ledger l "
           "JOIN items i ON i.id = l.item_id")
    params = []
    if item_id:
        sql += " WHERE l.item_id = ?"
        params.append(item_id)
    sql += " ORDER BY l.id"
    entries = []
    running = 0
    for r in conn.execute(sql, params).fetchall():
        e = dict(r)
        running += e["qty_change"]
        e["balance"] = running          # only meaningful when one item is chosen
        entries.append(e)
    items = conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()
    conn.close()
    return render_template("production/ledger.html", entries=entries, items=items,
                           item_id=item_id)
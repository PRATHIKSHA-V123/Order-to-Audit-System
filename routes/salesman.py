from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database.db import get_connection
from routes.auth import role_required
from services.orders import create_order

salesman_bp = Blueprint("salesman", __name__, url_prefix="/salesman")


@salesman_bp.route("/new-order", methods=["GET", "POST"])
@role_required("salesman")
def new_order():
    conn = get_connection()
    if request.method == "POST":
        customer_id = int(request.form["customer_id"])
        lines = []
        for key, value in request.form.items():
            if key.startswith("qty_") and value.strip():
                qty = int(value)
                if qty > 0:
                    lines.append((int(key[4:]), qty))
        if not lines:
            flash("Add a quantity for at least one product", "error")
        else:
            create_order(conn, customer_id, lines, session["user_id"])
            conn.commit()
            conn.close()
            flash("Order submitted to the factory")
            return redirect(url_for("salesman.my_orders"))

    customers = conn.execute("SELECT id, name, state FROM customers ORDER BY name").fetchall()
    products = conn.execute(
        "SELECT id, name, price_paise FROM items WHERE item_type = 'finished' ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("salesman/new_order.html", customers=customers, products=products)


@salesman_bp.route("/orders")
@role_required("salesman")
def my_orders():
    conn = get_connection()
    orders = conn.execute(
        "SELECT o.id, o.order_date, o.status, c.name AS customer, "
        "COALESCE(SUM(ol.qty_ordered * ol.rate_paise), 0) AS value_paise, "
        "EXISTS(SELECT 1 FROM invoices i WHERE i.order_id = o.id) AS has_invoice "
        "FROM orders o JOIN customers c ON c.id = o.customer_id "
        "LEFT JOIN order_lines ol ON ol.order_id = o.id "
        "WHERE o.created_by = ? GROUP BY o.id ORDER BY o.id DESC",
        (session["user_id"],),
    ).fetchall()
    by_customer = conn.execute(
        "SELECT c.name AS customer, COUNT(DISTINCT o.id) AS orders, "
        "SUM(ol.qty_ordered * ol.rate_paise) AS value_paise "
        "FROM orders o JOIN customers c ON c.id = o.customer_id "
        "JOIN order_lines ol ON ol.order_id = o.id "
        "WHERE o.created_by = ? AND o.status NOT IN ('rejected', 'cancelled') "
        "GROUP BY c.id ORDER BY value_paise DESC",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return render_template("salesman/my_orders.html", orders=orders, by_customer=by_customer)
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database.db import get_connection
from routes.auth import role_required
from services.audit import log
from services.stock import add_movement, format_qty

masters_bp = Blueprint("masters", __name__, url_prefix="/masters")

FACTOR = {"g": 1000, "ml": 1000, "pc": 1}
UNIT_NAMES = {"g": "kg", "ml": "L", "pc": "pieces"}
# A dropdown, so the state is always spelled exactly. It decides CGST/SGST or IGST.
STATES = ["Tamil Nadu", "Andhra Pradesh", "Karnataka", "Kerala", "Telangana", "Puducherry",
          "Maharashtra", "Gujarat", "Rajasthan", "Delhi", "Uttar Pradesh", "West Bengal",
          "Madhya Pradesh", "Punjab", "Haryana", "Odisha", "Bihar", "Assam", "Other state"]


def to_paise(text):
    return int((Decimal(text) * 100).quantize(Decimal("1"), ROUND_HALF_UP))


def to_base(text, unit):
    return int((Decimal(text) * FACTOR[unit]).quantize(Decimal("1"), ROUND_HALF_UP))


def back(error=None, message=None):
    if error:
        flash(error, "error")
    elif message:
        flash(message)
    return redirect(url_for("masters.index"))


@masters_bp.route("/")
@role_required("admin")
def index():
    conn = get_connection()
    items = conn.execute("SELECT * FROM items ORDER BY item_type DESC, id").fetchall()
    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    suppliers = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    boms = []
    for h in conn.execute(
        "SELECT h.id, h.product_id, h.planned_output, i.name "
        "FROM bom_header h JOIN items i ON i.id = h.product_id ORDER BY h.id"
    ).fetchall():
        lines = conn.execute(
            "SELECT bl.qty_per_batch, i.name, i.unit FROM bom_lines bl "
            "JOIN items i ON i.id = bl.item_id WHERE bl.bom_id = ? ORDER BY bl.id",
            (h["id"],),
        ).fetchall()
        boms.append({"header": h, "lines": lines})
    no_bom = conn.execute(
        "SELECT id, name FROM items WHERE item_type = 'finished' "
        "AND id NOT IN (SELECT product_id FROM bom_header)"
    ).fetchall()
    materials = [i for i in items if i["item_type"] in ("raw", "packing")]
    conn.close()
    return render_template("admin/masters.html", items=items, customers=customers,
                           suppliers=suppliers, boms=boms, no_bom=no_bom,
                           materials=materials, unit_names=UNIT_NAMES, states=STATES)


@masters_bp.route("/item", methods=["POST"])
@role_required("admin")
def add_item():
    name = request.form.get("name", "").strip()
    item_type = request.form.get("item_type")
    unit = request.form.get("unit")
    hsn = request.form.get("hsn", "").strip() or None
    try:
        price = to_paise(request.form.get("price") or "0")
        gst = int(request.form.get("gst") or 0)
    except (InvalidOperation, ValueError):
        return back(error="Enter valid numbers")
    if not name or item_type not in ("raw", "packing", "finished") or unit not in FACTOR:
        return back(error="Name, type and unit are needed")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO items (name, item_type, unit, price_paise, gst_percent, hsn_code) "
            "VALUES (?, ?, ?, ?, ?, ?)", (name, item_type, unit, price, gst, hsn))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return back(error="An item with this name already exists")
    finally:
        conn.close()
    return back(message=f"{name} added")


@masters_bp.route("/item/<int:item_id>", methods=["POST"])
@role_required("admin")
def update_item(item_id):
    try:
        price = to_paise(request.form["price"])
        gst = int(request.form["gst"])
        if price < 0 or not 0 <= gst <= 40:
            raise ValueError
    except (InvalidOperation, ValueError, KeyError):
        return back(error="Enter a valid price and GST %")
    hsn = request.form.get("hsn", "").strip() or None
    conn = get_connection()
    old = conn.execute("SELECT name, price_paise, gst_percent, hsn_code FROM items WHERE id = ?",
                       (item_id,)).fetchone()
    if old is None:
        conn.close()
        return back(error="Item not found")
    conn.execute("UPDATE items SET price_paise = ?, gst_percent = ?, hsn_code = ? WHERE id = ?",
                 (price, gst, hsn, item_id))
    if (old["price_paise"], old["gst_percent"], old["hsn_code"]) != (price, gst, hsn):
        log(conn, "items", item_id, "update",
            old=f"{old['name']}: Rs {old['price_paise'] / 100:.2f}, GST {old['gst_percent']}%, HSN {old['hsn_code']}",
            new=f"{old['name']}: Rs {price / 100:.2f}, GST {gst}%, HSN {hsn}",
            user_id=session["user_id"])
    conn.commit()
    conn.close()
    return back(message="Item updated. New orders use the new price; old orders keep theirs.")


@masters_bp.route("/customer", methods=["POST"])
@role_required("admin")
def add_customer():
    name = request.form.get("name", "").strip()
    state = request.form.get("state")
    if not name or state not in STATES:
        return back(error="Customer name and state are needed")
    conn = get_connection()
    conn.execute(
        "INSERT INTO customers (name, gstin, state, phone, address) VALUES (?, ?, ?, ?, ?)",
        (name, request.form.get("gstin", "").strip() or None, state,
         request.form.get("phone", "").strip() or None,
         request.form.get("address", "").strip() or None))
    conn.commit()
    conn.close()
    return back(message=f"{name} added")


@masters_bp.route("/supplier", methods=["POST"])
@role_required("admin")
def add_supplier():
    name = request.form.get("name", "").strip()
    if not name:
        return back(error="Supplier name is needed")
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO suppliers (name, phone, gstin, address) VALUES (?, ?, ?, ?)",
            (name, request.form.get("phone", "").strip() or None,
             request.form.get("gstin", "").strip() or None,
             request.form.get("address", "").strip() or None))
        log(conn, "suppliers", cur.lastrowid, "create", new=name, user_id=session["user_id"])
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return back(error="This supplier already exists")
    finally:
        conn.close()
    return back(message=f"{name} added")


@masters_bp.route("/adjust", methods=["POST"])
@role_required("admin")
def adjust_stock():
    reason = request.form.get("reason", "").strip()
    conn = get_connection()
    item = conn.execute("SELECT id, name, unit FROM items WHERE id = ?",
                        (request.form.get("item_id", type=int),)).fetchone()
    try:
        qty = to_base(request.form.get("qty", ""), item["unit"]) if item else 0
    except InvalidOperation:
        qty = 0
    if item is None or qty == 0 or not reason:
        conn.close()
        return back(error="Choose an item, enter a quantity (not zero) and give a reason")
    try:
        ledger_id = add_movement(conn, item["id"], qty, "adjustment", "items", item["id"], reason)
        log(conn, "stock_ledger", ledger_id, "adjustment",
            new=f"{item['name']}: {format_qty(item['unit'], qty)}. Reason: {reason}",
            user_id=session["user_id"])
        conn.commit()
    except ValueError:
        conn.rollback()
        return back(error="Not enough stock for this reduction")
    finally:
        conn.close()
    return back(message=f"{item['name']} adjusted by {format_qty(item['unit'], qty)}")


@masters_bp.route("/bom", methods=["POST"])
@role_required("admin")
def create_bom():
    try:
        product_id = int(request.form["product_id"])
        planned = int(request.form["planned_output"])
        if planned < 1:
            raise ValueError
    except (ValueError, KeyError):
        return back(error="Choose a product and enter the packets made by one batch")
    copy_from = request.form.get("copy_from", type=int)
    conn = get_connection()
    if conn.execute("SELECT 1 FROM bom_header WHERE product_id = ?", (product_id,)).fetchone():
        conn.close()
        return back(error="This product already has a BOM")
    cur = conn.execute("INSERT INTO bom_header (product_id, planned_output) VALUES (?, ?)",
                       (product_id, planned))
    if copy_from:
        src = conn.execute("SELECT id FROM bom_header WHERE product_id = ?", (copy_from,)).fetchone()
        if src:
            conn.execute(
                "INSERT INTO bom_lines (bom_id, item_id, qty_per_batch) "
                "SELECT ?, item_id, qty_per_batch FROM bom_lines WHERE bom_id = ?",
                (cur.lastrowid, src["id"]))
    conn.commit()
    conn.close()
    return back(message="BOM created. Check the quantities below.")


@masters_bp.route("/bom/<int:bom_id>/output", methods=["POST"])
@role_required("admin")
def set_output(bom_id):
    try:
        planned = int(request.form["planned_output"])
        if planned < 1:
            raise ValueError
    except (ValueError, KeyError):
        return back(error="Enter a valid number of packets")
    conn = get_connection()
    conn.execute("UPDATE bom_header SET planned_output = ? WHERE id = ?", (planned, bom_id))
    conn.commit()
    conn.close()
    return back(message="Expected yield updated")


@masters_bp.route("/bom/<int:bom_id>/line", methods=["POST"])
@role_required("admin")
def set_line(bom_id):
    conn = get_connection()
    try:
        item_id = int(request.form["item_id"])
        item = conn.execute(
            "SELECT unit FROM items WHERE id = ? AND item_type IN ('raw', 'packing')",
            (item_id,)).fetchone()
        if item is None:
            raise ValueError
        qty = to_base(request.form["qty"], item["unit"])
        if qty < 0:
            raise ValueError
    except (ValueError, KeyError, InvalidOperation):
        conn.close()
        return back(error="Choose a material and enter a valid quantity")
    existing = conn.execute(
        "SELECT id FROM bom_lines WHERE bom_id = ? AND item_id = ?", (bom_id, item_id)).fetchone()
    if qty == 0:
        if existing:
            conn.execute("DELETE FROM bom_lines WHERE id = ?", (existing["id"],))
    elif existing:
        conn.execute("UPDATE bom_lines SET qty_per_batch = ? WHERE id = ?", (qty, existing["id"]))
    else:
        conn.execute("INSERT INTO bom_lines (bom_id, item_id, qty_per_batch) VALUES (?, ?, ?)",
                     (bom_id, item_id, qty))
    conn.commit()
    conn.close()
    return back(message="BOM updated. Old production runs keep their own planned quantities.")
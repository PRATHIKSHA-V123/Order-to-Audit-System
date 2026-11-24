from database.db import get_connection


def balance(conn, item_id):
    """Stock balance = sum of all ledger movements for the item."""
    row = conn.execute(
        "SELECT COALESCE(SUM(qty_change), 0) AS bal FROM stock_ledger WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    return row["bal"]


def add_movement(conn, item_id, qty_change, txn_type,
                 ref_table=None, ref_id=None, note=None):
    """Every stock change goes through here, and is linked to its source document."""
    if qty_change < 0 and balance(conn, item_id) + qty_change < 0:
        raise ValueError("Not enough stock")
    cur = conn.execute(
        "INSERT INTO stock_ledger (item_id, qty_change, txn_type, ref_table, ref_id, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, qty_change, txn_type, ref_table, ref_id, note),
    )
    return cur.lastrowid


def record_purchase(conn, item_id, qty, total_paise, supplier=None, user_id=None):
    """Buy raw material: save the purchase and put it into the stock ledger."""
    cur = conn.execute(
        "INSERT INTO purchases (item_id, qty, total_paise, supplier, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (item_id, qty, total_paise, supplier, user_id),
    )
    add_movement(conn, item_id, qty, "purchase", "purchases", cur.lastrowid)
    return cur.lastrowid


def all_balances():
    """Current balance of every item (for the stock summary)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT i.id, i.name, i.item_type, i.unit, "
        "COALESCE(SUM(l.qty_change), 0) AS bal "
        "FROM items i LEFT JOIN stock_ledger l ON l.item_id = i.id "
        "GROUP BY i.id ORDER BY i.id"
    ).fetchall()
    conn.close()
    return rows


def format_qty(unit, qty):
    """Show base units in a friendly way: g -> kg, ml -> L."""
    if unit == "g":
        return f"{qty / 1000} kg"
    if unit == "ml":
        return f"{qty / 1000} L"
    return f"{qty} pieces"
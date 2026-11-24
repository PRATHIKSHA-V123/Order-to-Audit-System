from werkzeug.security import generate_password_hash
from database.db import get_connection
from services.stock import add_movement

# (username, password, full name, role)
USERS = [
    ("sales", "sales123", "Sita Salesman", "salesman"),
    ("admin", "admin123", "Prathiksha V", "admin"),
    ("prod", "prod123", "Prakash Production", "production"),
    ("acc", "acc123", "Anita Accountant", "accountant"),
    ("owner", "owner123", "Om Owner", "owner"),
]

# (name, type, unit, selling price in paise, gst %, hsn)
# Quantities are stored in base units: g, ml, pc
ITEMS = [
    ("Flour", "raw", "g", 0, 0, None),
    ("Cooking oil", "raw", "ml", 0, 0, None),
    ("Salt and spice mix", "raw", "g", 0, 0, None),
    ("200 g pouch", "packing", "pc", 0, 0, None),
    ("Carton (20 packets)", "packing", "pc", 0, 0, None),
    ("Murukku 200 g", "finished", "pc", 5000, 5, "2106"),
]

# (name, gstin, state, phone, address) - dummy data
CUSTOMERS = [
    ("Retailer A", "33AAAAA0000A1Z5", "Tamil Nadu", "9000000001", "Coimbatore"),
    ("Distributor B", "29BBBBB1111B1Z5", "Karnataka", "9000000002", "Bengaluru"),
]

# recipe for one batch (200 packets), in base units
BOM_LINES = [
    ("Flour", 40000),               # 40 kg
    ("Cooking oil", 10000),         # 10 L
    ("Salt and spice mix", 1200),   # 1.2 kg
    ("200 g pouch", 200),
    ("Carton (20 packets)", 10),
]

# opening stock: (name, qty in base unit, total value in paise)
OPENING = [
    ("Flour", 100000, 420000),              # 100 kg at Rs 42/kg
    ("Cooking oil", 30000, 420000),         # 30 L at Rs 140/L
    ("Salt and spice mix", 5000, 100000),   # 5 kg at Rs 200/kg
    ("200 g pouch", 500, 125000),           # 500 at Rs 2.50
    ("Carton (20 packets)", 30, 45000),     # 30 at Rs 15
]


def seed_users(conn):
    for username, password, full_name, role in USERS:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, full_name, role) "
            "VALUES (?, ?, ?, ?)",
            (username, generate_password_hash(password), full_name, role),
        )


def seed_master(conn):
    for name, t, unit, price, gst, hsn in ITEMS:
        conn.execute(
            "INSERT OR IGNORE INTO items (name, item_type, unit, price_paise, gst_percent, hsn_code) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, t, unit, price, gst, hsn),
        )
    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM items")}

    for name, gstin, state, phone, address in CUSTOMERS:
        if not conn.execute("SELECT 1 FROM customers WHERE name = ?", (name,)).fetchone():
            conn.execute(
                "INSERT INTO customers (name, gstin, state, phone, address) VALUES (?, ?, ?, ?, ?)",
                (name, gstin, state, phone, address),
            )

    product_id = ids["Murukku 200 g"]
    if not conn.execute("SELECT 1 FROM bom_header WHERE product_id = ?", (product_id,)).fetchone():
        cur = conn.execute(
            "INSERT INTO bom_header (product_id, planned_output, notes) VALUES (?, ?, ?)",
            (product_id, 200, "One batch makes 200 packets"),
        )
        for name, qty in BOM_LINES:
            conn.execute(
                "INSERT INTO bom_lines (bom_id, item_id, qty_per_batch) VALUES (?, ?, ?)",
                (cur.lastrowid, ids[name], qty),
            )

    # opening stock goes into the ledger, never typed in as a number
    if not conn.execute("SELECT 1 FROM stock_ledger WHERE txn_type = 'opening'").fetchone():
        for name, qty, total in OPENING:
            cur = conn.execute(
                "INSERT INTO purchases (item_id, qty, total_paise, supplier) VALUES (?, ?, ?, ?)",
                (ids[name], qty, total, "OPENING STOCK"),
            )
            add_movement(conn, ids[name], qty, "opening", "purchases", cur.lastrowid, "Opening balance")
        add_movement(conn, product_id, 50, "opening", None, None, "Opening finished goods")


if __name__ == "__main__":
    conn = get_connection()
    seed_users(conn)
    seed_master(conn)
    conn.commit()
    conn.close()
    print("Seed data loaded")
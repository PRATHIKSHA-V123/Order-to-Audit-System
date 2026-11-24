-- Money is in paise (integers). Quantities are in base units (g, ml, pc).

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('salesman','admin','production','accountant','owner')),
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gstin TEXT,
    state TEXT NOT NULL,
    phone TEXT,
    address TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    item_type TEXT NOT NULL CHECK (item_type IN ('raw','packing','finished')),
    unit TEXT NOT NULL CHECK (unit IN ('g','ml','pc')),
    price_paise INTEGER NOT NULL DEFAULT 0,
    gst_percent INTEGER NOT NULL DEFAULT 0,
    hsn_code TEXT
);

CREATE TABLE IF NOT EXISTS bom_header (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL UNIQUE REFERENCES items(id),
    planned_output INTEGER NOT NULL,      -- packets made by one standard batch
    notes TEXT
);

CREATE TABLE IF NOT EXISTS bom_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_id INTEGER NOT NULL REFERENCES bom_header(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    qty_per_batch INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id),
    qty INTEGER NOT NULL,
    total_paise INTEGER NOT NULL,
    supplier TEXT,
    purchase_date TEXT NOT NULL DEFAULT (date('now')),
    created_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS production_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES items(id),
    run_date TEXT NOT NULL DEFAULT (date('now')),
    planned_output INTEGER NOT NULL,
    actual_output INTEGER NOT NULL,
    labour_paise INTEGER NOT NULL DEFAULT 0,
    overhead_paise INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS production_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES production_runs(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    planned_qty INTEGER NOT NULL,
    actual_qty INTEGER NOT NULL
);

-- Stock is never typed in. Balance = SUM(qty_change) for an item.
CREATE TABLE IF NOT EXISTS stock_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id),
    qty_change INTEGER NOT NULL,          -- + in, - out
    txn_type TEXT NOT NULL CHECK (txn_type IN
        ('opening','purchase','production_use','production_output','damage','sale')),
    ref_table TEXT,
    ref_id INTEGER,
    txn_date TEXT NOT NULL DEFAULT (date('now')),
    note TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date TEXT NOT NULL DEFAULT (date('now')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','dispatched','cancelled')),
    created_by INTEGER REFERENCES users(id),
    approved_by INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    qty_ordered INTEGER NOT NULL,
    qty_dispatched INTEGER NOT NULL DEFAULT 0,
    rate_paise INTEGER NOT NULL,
    gst_percent INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL UNIQUE,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    invoice_date TEXT NOT NULL DEFAULT (date('now')),
    taxable_paise INTEGER NOT NULL,
    cgst_paise INTEGER NOT NULL DEFAULT 0,
    sgst_paise INTEGER NOT NULL DEFAULT 0,
    igst_paise INTEGER NOT NULL DEFAULT 0,
    total_paise INTEGER NOT NULL,
    pdf_path TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount_paise INTEGER NOT NULL,
    pay_date TEXT NOT NULL DEFAULT (date('now')),
    mode TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT NOT NULL, record_id INTEGER NOT NULL, action TEXT NOT NULL, old_value TEXT, new_value TEXT, user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS credit_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credit_no TEXT NOT NULL UNIQUE,
    invoice_id INTEGER NOT NULL UNIQUE REFERENCES invoices(id),
    note_date TEXT NOT NULL DEFAULT (date('now')),
    reason TEXT NOT NULL,
    taxable_paise INTEGER NOT NULL,
    cgst_paise INTEGER NOT NULL DEFAULT 0,
    sgst_paise INTEGER NOT NULL DEFAULT 0,
    igst_paise INTEGER NOT NULL DEFAULT 0,
    total_paise INTEGER NOT NULL,
    created_by INTEGER REFERENCES users(id)
);

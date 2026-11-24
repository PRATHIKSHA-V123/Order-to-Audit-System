import os

folders = [
    "database", "services", "routes",
    "templates/salesman", "templates/admin", "templates/production",
    "templates/accountant", "templates/owner",
    "static", "invoices", "exports", "tests",
]
files = [
    "config.py", "seed.py", "README.md", "DESIGN.md",
    "database/db.py", "database/schema.sql",
    "services/stock.py", "services/production.py", "services/orders.py",
    "services/gst.py", "services/costing.py", "services/pdf_invoice.py",
    "routes/auth.py", "routes/salesman.py", "routes/admin.py",
    "routes/production.py", "routes/accountant.py", "routes/owner.py",
    "templates/base.html", "templates/login.html", "static/style.css",
    "tests/test_stock.py", "tests/test_gst.py", "tests/test_benchmark.py",
]

for f in folders:
    os.makedirs(f, exist_ok=True)
for f in files:
    open(f, "a").close()

print("Folder structure created")
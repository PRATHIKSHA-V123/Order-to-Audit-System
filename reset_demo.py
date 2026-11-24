import os
from database.db import get_connection
from seed import seed_users, seed_master

HERE = os.path.dirname(os.path.abspath(__file__))

# find the database file that the app uses, then delete it
conn = get_connection()
path = conn.execute("PRAGMA database_list").fetchone()["file"]
conn.close()
if path and os.path.exists(path):
    os.remove(path)

# build a fresh one: tables, test users and the section 5 master data
conn = get_connection()
with open(os.path.join(HERE, "database", "schema.sql"), encoding="utf-8") as f:
    conn.executescript(f.read())
seed_users(conn)
seed_master(conn)
conn.commit()
conn.close()
print("Demo database reset. Opening stock is loaded and no orders exist.")
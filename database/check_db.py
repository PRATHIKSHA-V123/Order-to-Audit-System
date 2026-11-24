import sqlite3

conn = sqlite3.connect("factory.db")
rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
print("Number of tables:", len(rows))
for r in rows:
    print(" -", r[0])
conn.close()
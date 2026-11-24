import sqlite3
from pathlib import Path

# Folder paths (based on where this file is)
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "factory.db"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"


def get_connection():
    """Open a connection to factory.db."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row      # lets us use row["name"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables by running schema.sql."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    conn = get_connection()
    conn.executescript(sql)
    conn.commit()
    conn.close()
    print("Database created at:", DB_PATH)


if __name__ == "__main__":
    init_db()
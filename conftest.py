import os
import sqlite3
import pytest
from seed import seed_users, seed_master

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "schema.sql")


@pytest.fixture
def conn():
    """A fresh in-memory database with the benchmark master data, for every test."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA, encoding="utf-8") as f:
        c.executescript(f.read())
    seed_users(c)
    seed_master(c)
    c.commit()
    yield c
    c.close()
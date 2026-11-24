import pytest
from services.stock import balance, add_movement, record_purchase


def item_id(conn, name):
    return conn.execute("SELECT id FROM items WHERE name = ?", (name,)).fetchone()["id"]


def test_opening_balances_come_from_the_ledger(conn):
    assert balance(conn, item_id(conn, "Flour")) == 100000
    assert balance(conn, item_id(conn, "Cooking oil")) == 30000
    assert balance(conn, item_id(conn, "Murukku 200 g")) == 50


def test_purchase_increases_stock(conn):
    flour = item_id(conn, "Flour")
    record_purchase(conn, flour, 60000, 270000)
    assert balance(conn, flour) == 160000


def test_stock_cannot_go_below_zero(conn):
    fg = item_id(conn, "Murukku 200 g")
    with pytest.raises(ValueError):
        add_movement(conn, fg, -51, "sale")
    assert balance(conn, fg) == 50


def test_every_movement_links_to_its_source(conn):
    flour = item_id(conn, "Flour")
    purchase_id = record_purchase(conn, flour, 1000, 4500)
    row = conn.execute(
        "SELECT 1 FROM stock_ledger WHERE ref_table = 'purchases' AND ref_id = ?",
        (purchase_id,),
    ).fetchone()
    assert row is not None
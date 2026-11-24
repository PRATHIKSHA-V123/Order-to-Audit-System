from decimal import Decimal
from services.stock import add_movement
from services.audit import log

TOLERANCE_PERCENT = Decimal("3")   # variance beyond this is flagged


def variance_pct(planned, actual):
    """(actual - planned) / planned x 100, using Decimal so there are no float errors."""
    if planned == 0:
        return Decimal("0")
    diff = Decimal(actual) - Decimal(planned)
    return (diff * 100 / Decimal(planned)).quantize(Decimal("0.01"))


def is_flagged(pct):
    return abs(pct) > TOLERANCE_PERCENT


def get_bom(conn, product_id):
    header = conn.execute(
        "SELECT * FROM bom_header WHERE product_id = ?", (product_id,)
    ).fetchone()
    if header is None:
        raise ValueError("This product has no BOM")
    lines = conn.execute(
        "SELECT bl.item_id, bl.qty_per_batch, i.name, i.unit "
        "FROM bom_lines bl JOIN items i ON i.id = bl.item_id WHERE bl.bom_id = ?",
        (header["id"],),
    ).fetchall()
    return header, lines


def record_run(conn, product_id, batches, used, actual_output,
               damaged=None, labour_paise=0, overhead_paise=0, user_id=None):
    """
    Save one production run.
      used    = {item_id: quantity really consumed}  (includes damaged items)
      damaged = {item_id: quantity damaged}          (part of 'used')
    Raw and packing stock goes down, finished goods go up, all through the ledger.
    """
    damaged = damaged or {}
    header, lines = get_bom(conn, product_id)
    planned_output = header["planned_output"] * batches

    cur = conn.execute(
        "INSERT INTO production_runs (product_id, planned_output, actual_output, "
        "labour_paise, overhead_paise, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (product_id, planned_output, actual_output, labour_paise, overhead_paise, user_id),
    )
    run_id = cur.lastrowid

    for line in lines:
        item_id = line["item_id"]
        planned_qty = line["qty_per_batch"] * batches
        actual_qty = used.get(item_id, 0)
        bad = damaged.get(item_id, 0)

        conn.execute(
            "INSERT INTO production_lines (run_id, item_id, planned_qty, actual_qty) "
            "VALUES (?, ?, ?, ?)",
            (run_id, item_id, planned_qty, actual_qty),
        )
        if actual_qty - bad > 0:
            add_movement(conn, item_id, -(actual_qty - bad), "production_use",
                         "production_runs", run_id)
        if bad > 0:
            add_movement(conn, item_id, -bad, "damage", "production_runs", run_id,
                         "Damaged during production")

    add_movement(conn, product_id, actual_output, "production_output",
                 "production_runs", run_id)
    log(conn, "production_runs", run_id, "RUN_CREATED", None,
        f"planned {planned_output}, actual {actual_output}", user_id)
    return run_id


def run_report(conn, run_id):
    """Planned vs actual for the run: yield and every material, with flags."""
    run = conn.execute("SELECT * FROM production_runs WHERE id = ?", (run_id,)).fetchone()
    yield_pct = variance_pct(run["planned_output"], run["actual_output"])
    rows = conn.execute(
        "SELECT i.name, pl.planned_qty, pl.actual_qty "
        "FROM production_lines pl JOIN items i ON i.id = pl.item_id "
        "WHERE pl.run_id = ?", (run_id,),
    ).fetchall()
    lines = []
    for r in rows:
        pct = variance_pct(r["planned_qty"], r["actual_qty"])
        lines.append({"name": r["name"], "planned": r["planned_qty"],
                      "actual": r["actual_qty"], "pct": pct, "flag": is_flagged(pct)})
    return {
        "planned_output": run["planned_output"],
        "actual_output": run["actual_output"],
        "yield_pct": yield_pct,
        "yield_flag": is_flagged(yield_pct),
        "lines": lines,
    }
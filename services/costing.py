from decimal import Decimal, ROUND_HALF_UP


def avg_rate(conn, item_id):
    """Weighted average purchase rate per base unit (paise per g, ml or piece)."""
    row = conn.execute(
        "SELECT SUM(qty) AS q, SUM(total_paise) AS t FROM purchases WHERE item_id = ?",
        (item_id,),
    ).fetchone()
    if not row["q"]:
        return Decimal(0)
    return Decimal(row["t"]) / Decimal(row["q"])


def run_cost(conn, run_id):
    """
    Cost of one production run.
    Materials = quantity used (damaged included) x weighted average rate.
    Labour and overhead of the run are added, then divided by good packets.
    """
    run = conn.execute("SELECT * FROM production_runs WHERE id = ?", (run_id,)).fetchone()
    lines = conn.execute(
        "SELECT item_id, actual_qty FROM production_lines WHERE run_id = ?", (run_id,)
    ).fetchall()

    material = Decimal(0)
    for l in lines:
        material += Decimal(l["actual_qty"]) * avg_rate(conn, l["item_id"])
    material = material.quantize(Decimal("1"), ROUND_HALF_UP)

    total = material + run["labour_paise"] + run["overhead_paise"]
    per_packet = (total / Decimal(run["actual_output"])).quantize(Decimal("0.01"), ROUND_HALF_UP)

    selling = conn.execute(
        "SELECT price_paise FROM items WHERE id = ?", (run["product_id"],)
    ).fetchone()["price_paise"]
    margin = Decimal(selling) - per_packet
    margin_pct = (margin * 100 / Decimal(selling)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    return {
        "material": material,
        "labour": run["labour_paise"],
        "overhead": run["overhead_paise"],
        "total": total,
        "good_packets": run["actual_output"],
        "per_packet": per_packet,
        "selling": selling,
        "margin": margin,
        "margin_pct": margin_pct,
    }
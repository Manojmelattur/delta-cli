import sqlite3
from datetime import datetime, timezone

from delta_bt.store.db import connect


def _compare_strategies(conn) -> list:
    """Aggregate strategy performance from deployment_events.

    Fix 1: compare_strategies() does not exist in store/db.py.
    Implemented directly here using deployment_events and deployments tables.

    Returns list of dicts ordered by avg_return_pct DESC.
    """
    rows = conn.execute(
        """
        SELECT
            d.strategy,
            COUNT(DISTINCT d.id)                        AS bot_count,
            COUNT(e.id)                                 AS trade_count,
            AVG(e.pnl)                                  AS avg_pnl,
            SUM(e.pnl)                                  AS total_pnl,
            SUM(CASE WHEN e.pnl > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN e.pnl <= 0 THEN 1 ELSE 0 END) AS losses
        FROM deployments d
        JOIN deployment_events e ON e.deployment_id = d.id
        WHERE e.pnl IS NOT NULL
          AND d.strategy IS NOT NULL
        GROUP BY d.strategy
        HAVING COUNT(e.id) >= 5
        ORDER BY avg_pnl DESC
        """
    ).fetchall()

    result = []
    for r in rows:
        wins   = int(r["wins"]   or 0)
        losses = int(r["losses"] or 0)
        total  = wins + losses

        # Profit factor: gross profit / gross loss
        pf_row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN e.pnl > 0 THEN e.pnl ELSE 0 END) AS gross_profit,
                SUM(CASE WHEN e.pnl < 0 THEN ABS(e.pnl) ELSE 0 END) AS gross_loss
            FROM deployment_events e
            JOIN deployments d ON e.deployment_id = d.id
            WHERE d.strategy = ? AND e.pnl IS NOT NULL
            """,
            (r["strategy"],),
        ).fetchone()

        gross_profit = float(pf_row["gross_profit"] or 0)
        gross_loss   = float(pf_row["gross_loss"]   or 1)
        avg_pf       = gross_profit / gross_loss if gross_loss > 0 else 0.0

        result.append({
            "strategy":       r["strategy"],
            "bot_count":      int(r["bot_count"]   or 0),
            "trade_count":    int(r["trade_count"] or 0),
            "avg_pnl":        float(r["avg_pnl"]   or 0.0),
            "total_pnl":      float(r["total_pnl"] or 0.0),
            "avg_return_pct": float(r["avg_pnl"]   or 0.0),  # proxy for return
            "win_rate":       (wins / total * 100) if total > 0 else 0.0,
            "avg_pf":         avg_pf,
        })

    return result


def run(**kwargs):
    """
    Capital Allocator Task.
    Compares strategy performance and rebalances lot sizes:
      - Scales DOWN the worst performing strategy by 50%
      - Scales UP the best performing strategy by 25% (capped at max_lot_size)
    """
    max_lot_size = float(kwargs.get("max_lot_size", 10.0))
    now_str      = datetime.now(timezone.utc).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 2+3: named column access

        # Fix 1: use local _compare_strategies instead of non-existent import
        stats = _compare_strategies(conn)

    if not stats or len(stats) < 2:
        return (
            "Capital Allocator: Not enough historical strategy data to rebalance. "
            "Need at least 2 strategies with 5+ trades each."
        )

    best_strat  = stats[0]
    worst_strat = stats[-1]

    messages = [
        "Capital Allocator Rebalancing Report",
        f"  Top Strategy   : {best_strat['strategy']} "
        f"(Avg PnL={best_strat['avg_pnl']:.4f} "
        f"WR={best_strat['win_rate']:.1f}% "
        f"PF={best_strat['avg_pf']:.2f} "
        f"Trades={best_strat['trade_count']})",
        f"  Bottom Strategy: {worst_strat['strategy']} "
        f"(Avg PnL={worst_strat['avg_pnl']:.4f} "
        f"WR={worst_strat['win_rate']:.1f}% "
        f"PF={worst_strat['avg_pf']:.2f} "
        f"Trades={worst_strat['trade_count']})",
    ]

    actions = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # --- Scale DOWN worst strategy ---
        worst_name = worst_strat["strategy"]
        worst_bots = conn.execute(
            "SELECT id, name, size, open_side FROM deployments "
            "WHERE status='running' AND strategy=?",
            (worst_name,),
        ).fetchall()

        for b in worst_bots:
            current_size = float(b["size"] or 1)
            # Fix 4: enforce minimum lot size of 1 — Delta does not support fractional lots
            new_size = max(1, round(current_size * 0.5))
            if new_size < current_size:
                try:
                    with connect() as c:
                        c.execute(
                            "UPDATE deployments SET size=? WHERE id=?",
                            (new_size, b["id"]),
                        )
                    # Fix 5: log audit event
                    with connect() as c:
                        c.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'capital_allocator', ?)",
                            (
                                b["id"], now_str,
                                f"Size reduced {current_size} -> {new_size} "
                                f"(worst strategy: {worst_name} "
                                f"avg_pnl={worst_strat['avg_pnl']:.4f})"
                                + (" [position open — applies to next entry]"
                                   if b["open_side"] else ""),
                            ),
                        )
                    messages.append(
                        f"  Reduced size for {b['name']} ({worst_name}): "
                        f"{current_size} -> {new_size}"
                        + (" [position open — next entry]" if b["open_side"] else "")
                    )
                    actions += 1
                except Exception as e:
                    messages.append(f"ERR | {b['name']}: size reduction failed — {e}")

        if not worst_bots:
            messages.append(
                f"  No running bots using worst strategy ({worst_name}) to downscale."
            )

        # Fix 6: scale UP best strategy bots
        best_name = best_strat["strategy"]
        best_bots = conn.execute(
            "SELECT id, name, size, open_side FROM deployments "
            "WHERE status='running' AND strategy=?",
            (best_name,),
        ).fetchall()

        for b in best_bots:
            current_size = float(b["size"] or 1)
            # Scale up by 25%, capped at max_lot_size
            new_size = min(max_lot_size, max(1, round(current_size * 1.25)))
            if new_size > current_size:
                try:
                    with connect() as c:
                        c.execute(
                            "UPDATE deployments SET size=? WHERE id=?",
                            (new_size, b["id"]),
                        )
                    with connect() as c:
                        c.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'capital_allocator', ?)",
                            (
                                b["id"], now_str,
                                f"Size increased {current_size} -> {new_size} "
                                f"(best strategy: {best_name} "
                                f"avg_pnl={best_strat['avg_pnl']:.4f})"
                                + (" [position open — applies to next entry]"
                                   if b["open_side"] else ""),
                            ),
                        )
                    messages.append(
                        f"  Increased size for {b['name']} ({best_name}): "
                        f"{current_size} -> {new_size}"
                        + (" [position open — next entry]" if b["open_side"] else "")
                    )
                    actions += 1
                except Exception as e:
                    messages.append(f"ERR | {b['name']}: size increase failed — {e}")

        if not best_bots:
            messages.append(
                f"  No running bots using best strategy ({best_name}) to upscale."
            )

    if actions == 0:
        messages.append("No size changes applied.")

    return "### Capital Allocator\n\n" + "\n".join(messages)

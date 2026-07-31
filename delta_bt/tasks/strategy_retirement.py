"""Strategy Retirement Task

Monitors rolling win rate for each active strategy over the last
30 days. If a strategy's win rate drops below the retirement threshold,
all bots running that strategy are automatically paused to prevent
further capital loss.

Paused bots can be manually reviewed and restarted via the UI.
A deployment_events audit record is written for every action.

Params (set in task params_json):
    min_win_rate_pct    : Win rate below which a strategy is retired (default 40.0)
    min_trades          : Minimum trades required before retirement is considered (default 10)
    lookback_days       : Rolling window in days for win rate calculation (default 30)
    auto_pause          : If True, pauses bots using underperforming strategies (default False)
    venue_filter        : Only act on this venue e.g. "live", "paper" (default all)
"""
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.store.db import connect


def run(**kwargs):
    min_win_rate  = float(kwargs.get("min_win_rate_pct", 40.0))
    min_trades    = int(kwargs.get("min_trades",         10))
    lookback_days = int(kwargs.get("lookback_days",      30))
    auto_pause    = bool(kwargs.get("auto_pause",        False))
    venue_filter  = kwargs.get("venue_filter",           None)

    now_str = datetime.now(timezone.utc).isoformat() + "Z"
    since   = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Aggregate win rate per strategy over the lookback window
        strategy_stats = conn.execute(
            """
            SELECT
                d.strategy,
                COUNT(e.id)                                                 AS trades,
                SUM(CASE WHEN e.pnl > 0  THEN 1 ELSE 0 END)               AS wins,
                SUM(CASE WHEN e.pnl <= 0 THEN 1 ELSE 0 END)               AS losses,
                SUM(e.pnl)                                                  AS total_pnl,
                AVG(e.pnl)                                                  AS avg_pnl
            FROM deployment_events e
            JOIN deployments d ON e.deployment_id = d.id
            WHERE e.ts      >= ?
              AND e.pnl     IS NOT NULL
              AND d.strategy IS NOT NULL
            GROUP BY d.strategy
            ORDER BY trades DESC
            """,
            (since,),
        ).fetchall()

    if not strategy_stats:
        return (
            f"Strategy Retirement: No trade data found "
            f"in the last {lookback_days} days."
        )

    messages   = []
    evaluated  = 0
    retired    = 0
    healthy    = 0
    skipped    = 0
    errors     = []

    for stat in strategy_stats:
        strategy    = stat["strategy"]
        trades      = int(stat["trades"]    or 0)
        wins        = int(stat["wins"]      or 0)
        losses      = int(stat["losses"]    or 0)
        total_pnl   = float(stat["total_pnl"] or 0.0)
        avg_pnl     = float(stat["avg_pnl"]   or 0.0)
        win_rate    = (wins / trades * 100) if trades > 0 else 0.0

        if trades < min_trades:
            skipped += 1
            messages.append(
                f"SKIP | {strategy}: only {trades} trades "
                f"(need {min_trades} minimum) — not enough data"
            )
            continue

        evaluated += 1

        if win_rate >= min_win_rate:
            healthy += 1
            messages.append(
                f"OK   | {strategy}: "
                f"WR={win_rate:.1f}% "
                f"({wins}W/{losses}L) "
                f"PnL=${total_pnl:.2f} "
                f"avg=${avg_pnl:.4f} "
                f"trades={trades}"
            )
            continue

        # Strategy is underperforming
        retired += 1
        messages.append(
            f"RETIRE | {strategy}: "
            f"WR={win_rate:.1f}% below threshold {min_win_rate:.0f}% "
            f"({wins}W/{losses}L over {trades} trades) "
            f"PnL=${total_pnl:.2f}"
        )

        if not auto_pause:
            messages.append(
                f"  auto_pause=False — no action taken. "
                f"Set auto_pause=true in params_json to enable."
            )
            continue

        # Fetch all running bots using this strategy
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT id, name, venue
                FROM deployments
                WHERE status   = 'running'
                  AND strategy = ?
            """
            args = [strategy]
            if venue_filter:
                query += " AND venue = ?"
                args.append(venue_filter)
            bots = conn.execute(query, args).fetchall()

        if not bots:
            messages.append(
                f"  No running bots using {strategy} to pause."
            )
            continue

        for bot in bots:
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (bot["id"],),
                    )
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'strategy_retirement', ?)",
                        (
                            bot["id"], now_str,
                            f"Bot paused — strategy {strategy} retired. "
                            f"WR={win_rate:.1f}% below threshold "
                            f"{min_win_rate:.0f}% over {trades} trades "
                            f"({lookback_days}d window). "
                            f"Total PnL=${total_pnl:.2f}",
                        ),
                    )
                messages.append(
                    f"  Paused: {bot['name']} ({bot['venue']})"
                )
            except Exception as e:
                err = f"ERR | {bot['name']}: pause failed — {e}"
                errors.append(err)
                messages.append(f"  {err}")

    # Summary
    summary = (
        f"Strategy Retirement complete — "
        f"evaluated={evaluated}, "
        f"healthy={healthy}, "
        f"retired={retired}, "
        f"skipped_low_data={skipped}"
    )
    messages.insert(0, summary)

    if not auto_pause and retired > 0:
        messages.append(
            "Note: Set auto_pause=true in params_json to automatically "
            "pause underperforming strategies."
        )

    if errors:
        messages.append("Errors:")
        messages.extend(errors)

    return "### Strategy Retirement\n\n" + "\n".join(messages)

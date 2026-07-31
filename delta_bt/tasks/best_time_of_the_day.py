"""Best Time of Day Analyzer Task

Analyzes deployment_events by hour of day (UTC) to find which
hours produce the most wins, highest PnL, and best win rate.

Produces a ranked hourly breakdown so you can:
  - Schedule auto-deploy tasks to only run during high-performance hours
  - Pause bots during historically losing hours
  - Understand session-based performance (Asia / London / New York)

Sessions (UTC):
  Asia          : 00:00 - 08:00
  London        : 08:00 - 16:00
  New York      : 13:00 - 21:00
  London+NY     : 13:00 - 16:00 (overlap — highest liquidity)
  Off Hours     : 21:00 - 00:00

Params (set in task params_json):
    lookback_days       : How many days of history to analyse (default 90)
    min_trades_per_hour : Minimum trades in an hour bucket to include (default 3)
    strategy_filter     : Only analyse this strategy (default all)
    venue_filter        : Only analyse this venue (default all)
    top_n               : Number of top/bottom hours to highlight (default 5)
"""
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.store.db import connect


_SESSIONS = {
    "Asia":        range(0,  8),
    "London":      range(8,  13),
    "London+NY":   range(13, 16),
    "New York":    range(16, 21),
    "Off Hours":   range(21, 24),
}


def _session_for(hour: int) -> str:
    """Return the trading session name for a given UTC hour."""
    for name, hours in _SESSIONS.items():
        if hour in hours:
            return name
    return "Unknown"


def run(**kwargs):
    lookback_days       = int(kwargs.get("lookback_days",        90))
    min_trades_per_hour = int(kwargs.get("min_trades_per_hour",  3))
    strategy_filter     = kwargs.get("strategy_filter",          None)
    venue_filter        = kwargs.get("venue_filter",             None)
    top_n               = int(kwargs.get("top_n",                5))

    since = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Extract hour from event timestamp and aggregate by hour
        query = """
            SELECT
                CAST(strftime('%H', e.ts) AS INTEGER)          AS hour,
                COUNT(e.id)                                     AS trades,
                SUM(CASE WHEN e.pnl > 0  THEN 1 ELSE 0 END)   AS wins,
                SUM(CASE WHEN e.pnl <= 0 THEN 1 ELSE 0 END)   AS losses,
                SUM(e.pnl)                                      AS total_pnl,
                AVG(e.pnl)                                      AS avg_pnl,
                MAX(e.pnl)                                      AS best_trade,
                MIN(e.pnl)                                      AS worst_trade
            FROM deployment_events e
            JOIN deployments d ON e.deployment_id = d.id
            WHERE e.ts     >= ?
              AND e.pnl    IS NOT NULL
        """
        args = [since]

        if strategy_filter:
            query += " AND d.strategy = ?"
            args.append(strategy_filter)
        if venue_filter:
            query += " AND d.venue = ?"
            args.append(venue_filter)

        query += " GROUP BY hour ORDER BY hour ASC"

        rows = conn.execute(query, args).fetchall()

    if not rows:
        return (
            f"Best Time of Day: No trade data found "
            f"in the last {lookback_days} days."
        )

    # Build hourly stats — fill missing hours with zeros
    hourly: dict = {}
    for row in rows:
        hour        = int(row["hour"])
        trades      = int(row["trades"]      or 0)
        wins        = int(row["wins"]        or 0)
        losses      = int(row["losses"]      or 0)
        total_pnl   = float(row["total_pnl"] or 0.0)
        avg_pnl     = float(row["avg_pnl"]   or 0.0)
        best_trade  = float(row["best_trade"] or 0.0)
        worst_trade = float(row["worst_trade"] or 0.0)
        win_rate    = (wins / trades * 100) if trades > 0 else 0.0

        hourly[hour] = {
            "hour":        hour,
            "trades":      trades,
            "wins":        wins,
            "losses":      losses,
            "total_pnl":   total_pnl,
            "avg_pnl":     avg_pnl,
            "best_trade":  best_trade,
            "worst_trade": worst_trade,
            "win_rate":    win_rate,
            "session":     _session_for(hour),
        }

    # Filter to hours with enough trades
    qualified = [
        h for h in hourly.values()
        if h["trades"] >= min_trades_per_hour
    ]

    if not qualified:
        return (
            f"Best Time of Day: No hours have at least "
            f"{min_trades_per_hour} trades in the last {lookback_days} days."
        )

    # Sort by total PnL descending for top/bottom ranking
    by_pnl     = sorted(qualified, key=lambda x: x["total_pnl"], reverse=True)
    by_winrate = sorted(qualified, key=lambda x: x["win_rate"],   reverse=True)

    top_pnl    = by_pnl[:top_n]
    bottom_pnl = by_pnl[-top_n:]
    top_wr     = by_winrate[:top_n]

    # Session-level aggregation
    session_stats: dict = {}
    for h in qualified:
        s = h["session"]
        if s not in session_stats:
            session_stats[s] = {
                "trades": 0, "wins": 0,
                "total_pnl": 0.0, "hours": 0,
            }
        session_stats[s]["trades"]    += h["trades"]
        session_stats[s]["wins"]      += h["wins"]
        session_stats[s]["total_pnl"] += h["total_pnl"]
        session_stats[s]["hours"]     += 1

    # Build report
    filters = []
    if strategy_filter: filters.append(f"strategy={strategy_filter}")
    if venue_filter:    filters.append(f"venue={venue_filter}")
    filter_str = ", ".join(filters) if filters else "all strategies and venues"

    lines = [
        f"Best Time of Day Analysis",
        f"  Lookback  : {lookback_days} days",
        f"  Filters   : {filter_str}",
        f"  Min trades: {min_trades_per_hour} per hour",
        f"  Hours with data: {len(qualified)}/24",
        "",
    ]

    # Full hourly table
    lines.append("Hourly Breakdown (UTC):")
    lines.append(
        f"  {'Hour':>4} {'Session':>12} {'Trades':>7} "
        f"{'Wins':>5} {'Losses':>7} {'WR%':>6} "
        f"{'Total PnL':>11} {'Avg PnL':>9}"
    )
    lines.append("  " + "-" * 75)

    for hour in range(24):
        if hour not in hourly:
            lines.append(
                f"  {hour:02d}:00 {'':>12} {'—':>7} "
                f"{'—':>5} {'—':>7} {'—':>6} "
                f"{'—':>11} {'—':>9}"
            )
            continue
        h = hourly[hour]
        if h["trades"] < min_trades_per_hour:
            marker = " (low data)"
        else:
            marker = ""
        lines.append(
            f"  {hour:02d}:00 {h['session']:>12} {h['trades']:>7} "
            f"{h['wins']:>5} {h['losses']:>7} {h['win_rate']:>5.1f}% "
            f"${h['total_pnl']:>10.2f} ${h['avg_pnl']:>8.4f}"
            f"{marker}"
        )

    # Session summary
    lines.append("")
    lines.append("Session Summary:")
    lines.append(
        f"  {'Session':>12} {'Trades':>7} {'WR%':>6} {'Total PnL':>11}"
    )
    lines.append("  " + "-" * 40)
    for session_name, ss in sorted(
        session_stats.items(),
        key=lambda x: x[1]["total_pnl"],
        reverse=True,
    ):
        wr = (ss["wins"] / ss["trades"] * 100) if ss["trades"] > 0 else 0.0
        lines.append(
            f"  {session_name:>12} {ss['trades']:>7} "
            f"{wr:>5.1f}% ${ss['total_pnl']:>10.2f}"
        )

    # Top hours by PnL
    lines.append("")
    lines.append(f"Top {top_n} Hours by Total PnL:")
    for h in top_pnl:
        lines.append(
            f"  {h['hour']:02d}:00 UTC ({h['session']:>12}) — "
            f"PnL=${h['total_pnl']:.2f} "
            f"WR={h['win_rate']:.1f}% "
            f"trades={h['trades']}"
        )

    # Bottom hours by PnL
    lines.append("")
    lines.append(f"Bottom {top_n} Hours by Total PnL:")
    for h in reversed(bottom_pnl):
        lines.append(
            f"  {h['hour']:02d}:00 UTC ({h['session']:>12}) — "
            f"PnL=${h['total_pnl']:.2f} "
            f"WR={h['win_rate']:.1f}% "
            f"trades={h['trades']}"
        )

    # Top hours by win rate
    lines.append("")
    lines.append(f"Top {top_n} Hours by Win Rate:")
    for h in top_wr:
        lines.append(
            f"  {h['hour']:02d}:00 UTC ({h['session']:>12}) — "
            f"WR={h['win_rate']:.1f}% "
            f"PnL=${h['total_pnl']:.2f} "
            f"trades={h['trades']}"
        )

    # Best and worst single trades
    all_best  = max(qualified, key=lambda x: x["best_trade"])
    all_worst = min(qualified, key=lambda x: x["worst_trade"])
    lines.append("")
    lines.append(
        f"Best single trade  : ${all_best['best_trade']:.4f} "
        f"at {all_best['hour']:02d}:00 UTC ({all_best['session']})"
    )
    lines.append(
        f"Worst single trade : ${all_worst['worst_trade']:.4f} "
        f"at {all_worst['hour']:02d}:00 UTC ({all_worst['session']})"
    )

    return "### Best Time of Day Analysis\n\n" + "\n".join(lines)

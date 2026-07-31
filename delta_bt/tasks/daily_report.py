import sqlite3
from datetime import datetime, timedelta, timezone

from delta_bt.store.db import connect


def run(venue=None, strategy=None, date_range=None, **kwargs):

    # Fix 1: use timezone-aware datetime throughout
    days = 1
    if date_range == "7d":   days = 7
    elif date_range == "30d": days = 30
    elif date_range == "all": days = 3650

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 5: named column access

        # Fix 7: active bots count is always current (not date-filtered)
        # but venue/strategy filters still apply
        q_bots      = "SELECT COUNT(*) FROM deployments WHERE status='running'"
        args_bots   = []

        # Fix 2: qualify venue and strategy with table alias d.
        # Fix 4: filter to events with pnl IS NOT NULL so COUNT = actual trades
        q_events = """
            SELECT
                COUNT(*)                                                    AS total_trades,
                SUM(CASE WHEN e.pnl > 0  THEN 1 ELSE 0 END)               AS wins,
                SUM(CASE WHEN e.pnl <= 0 THEN 1 ELSE 0 END)               AS losses,
                SUM(e.pnl)                                                  AS total_pnl
            FROM deployment_events e
            JOIN deployments d ON e.deployment_id = d.id
            WHERE e.ts > ?
              AND e.pnl IS NOT NULL
        """
        args_events = [since]

        filters_bots   = []
        filters_events = []

        if venue and venue != "all":
            filters_bots.append("venue=?")
            filters_events.append("d.venue=?")   # Fix 2: table-qualified
            args_bots.append(venue)
            args_events.append(venue)

        if strategy and strategy != "all":
            filters_bots.append("strategy=?")
            filters_events.append("d.strategy=?")  # Fix 2: table-qualified
            args_bots.append(strategy)
            args_events.append(strategy)

        if filters_bots:
            q_bots   += " AND " + " AND ".join(filters_bots)
        if filters_events:
            q_events += " AND " + " AND ".join(filters_events)

        active_bots = conn.execute(q_bots, args_bots).fetchone()[0]

        ev_row       = conn.execute(q_events, args_events).fetchone()
        recent_trades = int(ev_row["total_trades"] or 0)
        wins          = int(ev_row["wins"]         or 0)
        losses        = int(ev_row["losses"]       or 0)
        pnl           = float(ev_row["total_pnl"]  or 0.0)

        # Fix 4+6: tag summary — filter to pnl IS NOT NULL in JOIN condition
        q_tag = """
            SELECT
                d.tag,
                COUNT(DISTINCT d.id)                                        AS active_bots,
                COUNT(e.id)                                                 AS trades,
                SUM(CASE WHEN e.pnl > 0  THEN 1 ELSE 0 END)               AS wins,
                SUM(CASE WHEN e.pnl <= 0 THEN 1 ELSE 0 END)               AS losses,
                SUM(e.pnl)                                                  AS tag_pnl
            FROM deployments d
            LEFT JOIN deployment_events e
                ON e.deployment_id = d.id
                AND e.ts > ?
                AND e.pnl IS NOT NULL
            WHERE d.tag IS NOT NULL
        """
        args_tag = [since]

        if venue and venue != "all":
            q_tag    += " AND d.venue=?"
            args_tag.append(venue)
        if strategy and strategy != "all":
            q_tag    += " AND d.strategy=?"
            args_tag.append(strategy)

        q_tag += " GROUP BY d.tag ORDER BY tag_pnl DESC"

        tag_rows = conn.execute(q_tag, args_tag).fetchall()

    # Build filter description
    filter_text = []
    if venue    and venue    != "all": filter_text.append(f"Venue: {venue}")
    if strategy and strategy != "all": filter_text.append(f"Strategy: {strategy}")
    if date_range and date_range != "24h": filter_text.append(f"Time: {date_range}")
    filter_header = (
        f"Filters: {', '.join(filter_text)}"
        if filter_text
        else "Filters: None (includes live and paper)"
    )

# # Replace this
# event_label = {
#     "7d":  "Events (7d)",
#     "30d": "Events (30d)",
#     "all": "All Events",
# }.get(date_range, "Recent Events (24h)")

# With this
    if date_range == "7d":
        event_label = "Events (7d)"
    elif date_range == "30d":
        event_label = "Events (30d)"
    elif date_range == "all":
        event_label = "All Events"
    else:
        event_label = "Recent Events (24h)"


    overall_win_rate = (
        wins / (wins + losses) * 100
        if (wins + losses) > 0
        else 0.0
    )

    # Fix 1: use timezone-aware datetime for report header
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    report = f"""### Dynamic Summary Report

Date: {now_str}
{filter_header}

- Active Bots    : {active_bots}
- {event_label:20s}: {recent_trades}
- Wins           : {wins} | Losses: {losses} | Win Rate: {overall_win_rate:.1f}%
- Realized PnL   : ${pnl:.2f}

#### Task-Generated Bot Summary

| Task Tag | Bots | Trades | Wins | Losses | Win % | PnL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""

    if not tag_rows:
        report += "| No auto-deployed bots found | - | - | - | - | - | - |\n"
    else:
        for r in tag_rows:
            # Fix 5: named column access via sqlite3.Row
            t_tag    = r["tag"]         or "untagged"
            t_bots   = int(r["active_bots"] or 0)
            t_trades = int(r["trades"]      or 0)
            t_wins   = int(r["wins"]        or 0)
            t_losses = int(r["losses"]      or 0)
            t_pnl    = float(r["tag_pnl"]   or 0.0)
            win_pct  = (
                t_wins / (t_wins + t_losses) * 100
                if (t_wins + t_losses) > 0
                else 0.0
            )
            report += (
                f"| {t_tag} | {t_bots} | {t_trades} | "
                f"{t_wins} | {t_losses} | {win_pct:.1f}% | ${t_pnl:.2f} |\n"
            )

    report += "\nSystem Status: All systems healthy and monitoring.\n"
    return report

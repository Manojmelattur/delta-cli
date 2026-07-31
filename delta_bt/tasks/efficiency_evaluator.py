import sqlite3
from datetime import datetime, timezone

from delta_bt.store.db import connect


def run(**kwargs):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 4: named column access

        # Fix 1+2+6: read from deployment_events with kind='emergency_monitor'
        # instead of non-existent task_logs table with hardcoded task_id=1
        em_logs = conn.execute(
            "SELECT message FROM deployment_events "
            "WHERE kind='emergency_monitor'"
        ).fetchall()

        windfall_count  = 0
        ratchet_count   = 0
        breakeven_count = 0
        tier1_count     = 0
        tier2_count     = 0

        for r in em_logs:
            msg = r["message"] or ""
            if "[Windfall]"  in msg: windfall_count  += 1
            if "[Ratchet]"   in msg: ratchet_count   += 1
            if "[Breakeven]" in msg: breakeven_count += 1
            if "[Tier 1]"    in msg: tier1_count     += 1
            if "[Tier 2]"    in msg: tier2_count     += 1

        # Fix 3+7: use COALESCE to handle NULL realized_pnl
        # and use total_closed as denominator for win rate
        pnl_stats = conn.execute(
            """
            SELECT
                COUNT(*) AS total_closed,
                SUM(CASE WHEN COALESCE(realized_pnl, 0) > 0  THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN COALESCE(realized_pnl, 0) <= 0 THEN 1 ELSE 0 END) AS losses,
                SUM(COALESCE(realized_pnl, 0)) AS total_pnl
            FROM deployments
            WHERE status IN ('stopped', 'paused')
            AND realized_pnl IS NOT NULL
            """
        ).fetchone()

        total_closed = int(pnl_stats["total_closed"]  or 0)
        wins         = int(pnl_stats["wins"]          or 0)
        losses       = int(pnl_stats["losses"]        or 0)
        total_pnl    = float(pnl_stats["total_pnl"]   or 0.0)

        # Fix 7: use total_closed as denominator — wins+losses may be < total_closed
        # if some bots have NULL realized_pnl (already filtered above with IS NOT NULL)
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0

        # Also fetch currently running bots summary for context
        running_stats = conn.execute(
            """
            SELECT
                COUNT(*) AS total_running,
                SUM(CASE WHEN open_side IS NOT NULL THEN 1 ELSE 0 END) AS in_position,
                SUM(CASE WHEN open_side IS NULL     THEN 1 ELSE 0 END) AS flat
            FROM deployments
            WHERE status='running'
            """
        ).fetchone()

        total_running = int(running_stats["total_running"] or 0)
        in_position   = int(running_stats["in_position"]   or 0)
        flat_bots     = int(running_stats["flat"]          or 0)

    report = f"""### Efficiency Evaluator Report

Date: {now_str}

This report measures the actual impact of institutional risk-management features
by reading directly from deployment audit events.

#### Profit-Capture Metrics
- Windfall Catcher Engagements  : {windfall_count}
- Aggressive Ratchet Engagements: {ratchet_count}
- Breakeven Lock Engagements    : {breakeven_count}

#### Drawdown Prevention Metrics
- Tier 1 Emergency Engagements  : {tier1_count}
- Tier 2 Emergency Engagements  : {tier2_count}

#### Live Bot Status
- Total Running Bots : {total_running}
- In Position        : {in_position}
- Flat (waiting)     : {flat_bots}

#### Overall Closed Performance
- Total Closed Bots  : {total_closed}
- Global Win Rate    : {win_rate:.1f}% ({wins}W / {losses}L)
- Total Realized PnL : ${total_pnl:.2f}

Note: As profit-capture mechanisms engage more frequently, the global win rate
should stabilize and average loss per trade should decrease over time.
"""

    return report

"""Max Drawdown Guard Task

Monitors total realized PnL across all running deployments.
If daily or weekly drawdown exceeds the configured threshold,
pauses all live bots and logs a circuit-breaker event.

Params (set in task params_json):
    daily_drawdown_limit_usd  : Max allowed daily loss in USD (default 500)
    weekly_drawdown_limit_usd : Max allowed weekly loss in USD (default 1500)
    auto_pause                : If True, pauses all running bots (default False)
"""
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.store.db import connect


def run(**kwargs):
    daily_limit  = float(kwargs.get("daily_drawdown_limit_usd",  500.0))
    weekly_limit = float(kwargs.get("weekly_drawdown_limit_usd", 1500.0))
    auto_pause   = bool(kwargs.get("auto_pause", False))

    now     = datetime.now(timezone.utc)
    now_str = now.isoformat() + "Z"
    day_ago = (now - timedelta(days=1)).isoformat()  + "Z"
    week_ago= (now - timedelta(days=7)).isoformat()  + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Sum realized PnL from closed trade events in the last 24h
        daily_row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS total
            FROM deployment_events
            WHERE ts >= ?
              AND pnl IS NOT NULL
            """,
            (day_ago,),
        ).fetchone()

        # Sum realized PnL from closed trade events in the last 7 days
        weekly_row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS total
            FROM deployment_events
            WHERE ts >= ?
              AND pnl IS NOT NULL
            """,
            (week_ago,),
        ).fetchone()

        daily_pnl  = float(daily_row["total"]  or 0.0)
        weekly_pnl = float(weekly_row["total"] or 0.0)

        # Fetch all running deployments for pause action
        running = conn.execute(
            "SELECT id, name, venue FROM deployments WHERE status='running'"
        ).fetchall()

    messages = [
        "Max Drawdown Guard Report:",
        f"  Daily  PnL  : ${daily_pnl:.2f}  (limit=${daily_limit:.2f})",
        f"  Weekly PnL  : ${weekly_pnl:.2f}  (limit=${weekly_limit:.2f})",
        f"  Running Bots: {len(running)}",
    ]

    daily_breached  = daily_pnl  < -abs(daily_limit)
    weekly_breached = weekly_pnl < -abs(weekly_limit)

    if not daily_breached and not weekly_breached:
        messages.append("Status: All drawdown limits within safe bounds.")
        return "### Max Drawdown Guard\n\n" + "\n".join(messages)

    # Determine which limit was breached
    breach_reasons = []
    if daily_breached:
        breach_reasons.append(
            f"daily PnL ${daily_pnl:.2f} breached limit ${-daily_limit:.2f}"
        )
    if weekly_breached:
        breach_reasons.append(
            f"weekly PnL ${weekly_pnl:.2f} breached limit ${-weekly_limit:.2f}"
        )

    messages.append(
        f"BREACH DETECTED: {' | '.join(breach_reasons)}"
    )

    if not auto_pause:
        messages.append(
            "auto_pause=False — no action taken. "
            "Set auto_pause=true in params_json to enable automatic pausing."
        )
        return "### Max Drawdown Guard\n\n" + "\n".join(messages)

    # Pause all running bots
    paused  = 0
    errors  = []

    for bot in running:
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
                    "VALUES (?, ?, 'max_drawdown_guard', ?)",
                    (
                        bot["id"], now_str,
                        f"Paused by max drawdown guard — "
                        f"{' | '.join(breach_reasons)}",
                    ),
                )
            paused += 1
        except Exception as e:
            errors.append(f"ERR | {bot['name']}: {e}")

    messages.append(
        f"ACTION: Paused {paused} of {len(running)} running bots."
    )
    if errors:
        messages.extend(errors)

    return "### Max Drawdown Guard\n\n" + "\n".join(messages)

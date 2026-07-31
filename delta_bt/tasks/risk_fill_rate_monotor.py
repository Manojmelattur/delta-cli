"""Fill Rate Monitor Task.

Tracks the ratio of intended signals to actual fills per deployment.
Pauses a deployment if its fill rate drops below a threshold, which
indicates API issues, order rejections, or liquidity problems.

Fill rate = filled_orders / intended_signals

Requires deployment_events to log both:
    - kind='signal'  when a BUY/SELL signal is generated
    - kind='entry'   when an order is actually filled

Runs every 4 hours (interval_sec=14400).

Kwargs:
    fill_rate_threshold  (float, default 0.8)  — Min acceptable fill rate.
    lookback_signals     (int,   default 20)   — Recent signals to evaluate.
    action               (str,   default "alert") — alert | pause.
    dry_run              (bool,  default False).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_FILL_RATE_THRESHOLD = 0.8
DEFAULT_LOOKBACK_SIGNALS    = 20


def _log_event(dep_id: int, kind: str, message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO deployment_events"
                "(deployment_id, ts, kind, message) VALUES (?, ?, ?, ?)",
                (dep_id, ts, kind, message),
            )
    except Exception as e:
        logger.warning(f"FillRateMonitor: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Fill Rate Monitor Task.

    Kwargs:
        fill_rate_threshold (float, default 0.8)
        lookback_signals    (int,   default 20)
        action              (str,   default "alert") — alert | pause
        dry_run             (bool,  default False)
    """
    threshold = float(kwargs.get("fill_rate_threshold", DEFAULT_FILL_RATE_THRESHOLD))
    lookback  = int(kwargs.get("lookback_signals",      DEFAULT_LOOKBACK_SIGNALS))
    action    = str(kwargs.get("action",                "alert"))
    dry_run   = bool(kwargs.get("dry_run",              False))

    if action not in ("alert", "pause"):
        action = "alert"

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    flagged  = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        deps = conn.execute(
            "SELECT id, name, symbol FROM deployments WHERE status='running'"
        ).fetchall()

    if not deps:
        return "Fill Rate Monitor: No running deployments found."

    for dep in deps:
        dep_id = dep["id"]
        name   = dep["name"]
        symbol = dep["symbol"]

        with connect() as conn:
            signals = conn.execute(
                """
                SELECT COUNT(*) FROM deployment_events
                WHERE deployment_id = ?
                  AND kind = 'signal'
                ORDER BY ts DESC
                LIMIT ?
                """,
                (dep_id, lookback),
            ).fetchone()[0]

            fills = conn.execute(
                """
                SELECT COUNT(*) FROM deployment_events
                WHERE deployment_id = ?
                  AND kind = 'entry'
                ORDER BY ts DESC
                LIMIT ?
                """,
                (dep_id, lookback),
            ).fetchone()[0]

        if signals == 0:
            continue

        fill_rate = fills / signals

        msg = (
            f"{name} ({symbol}): fill_rate={fill_rate:.1%} "
            f"({fills}/{signals} signals filled, "
            f"threshold={threshold:.1%})"
        )

        if fill_rate >= threshold:
            messages.append(f"OK  | {msg}")
            continue

        flagged += 1

        if dry_run:
            messages.append(f"DRY | ALERT | {msg}")
            continue

        if action == "alert":
            messages.append(f"ALERT | {msg}")
            _log_event(dep_id, "fill_rate_alert", msg)

        elif action == "pause":
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (dep_id,),
                    )
                messages.append(f"PAUSE | {msg}")
                _log_event(dep_id, "fill_rate_pause", msg)
            except Exception as e:
                messages.append(f"ERR | {name} ({symbol}): pause failed — {e}")

    summary = (
        f"Fill Rate Monitor complete — "
        f"checked={len(deps)}, flagged={flagged}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

"""Margin Utilisation Guard Task.

Monitors total margin used across all open positions and blocks new
entries (by pausing deployments) when utilisation exceeds a threshold.

Margin utilisation = total_position_notional / (capital * leverage)

Runs every 15 minutes (interval_sec=900).

Kwargs:
    margin_threshold_pct (float, default 70.0) — Max utilisation % before action.
    capital              (float, default 10000) — Total account capital.
    leverage             (float, default 1.0)   — Account leverage.
    action               (str,   default "alert") — alert | pause_new.
    dry_run              (bool,  default False).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_MARGIN_THRESHOLD = 70.0
DEFAULT_CAPITAL          = 10_000.0
DEFAULT_LEVERAGE         = 1.0


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
        logger.warning(f"MarginGuard: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Margin Utilisation Guard Task.

    Kwargs:
        margin_threshold_pct (float, default 70.0)
        capital              (float, default 10000)
        leverage             (float, default 1.0)
        action               (str,   default "alert") — alert | pause_new
        dry_run              (bool,  default False)
    """
    threshold = float(kwargs.get("margin_threshold_pct", DEFAULT_MARGIN_THRESHOLD))
    capital   = float(kwargs.get("capital",              DEFAULT_CAPITAL))
    leverage  = float(kwargs.get("leverage",             DEFAULT_LEVERAGE))
    action    = str(kwargs.get("action",                 "alert"))
    dry_run   = bool(kwargs.get("dry_run",               False))

    if action not in ("alert", "pause_new"):
        action = "alert"

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, open_qty, open_price, leverage
            FROM deployments
            WHERE status   = 'running'
              AND open_side IS NOT NULL
              AND open_qty  > 0
            """
        ).fetchall()

    if not rows:
        return "Margin Utilisation Guard: No open positions found."

    # Calculate total notional across all open positions.
    total_notional = 0.0
    position_lines = []
    for row in rows:
        qty      = float(row["open_qty"]   or 0)
        price    = float(row["open_price"] or 0)
        lev      = float(row["leverage"]   or leverage)
        notional = qty * price / lev
        total_notional += notional
        position_lines.append(
            f"  {row['name']} ({row['symbol']}): "
            f"notional=${notional:,.2f}"
        )

    max_margin    = capital * leverage
    utilisation   = (total_notional / max_margin * 100.0) if max_margin > 0 else 0.0

    messages.append(
        f"Margin utilisation: {utilisation:.1f}% "
        f"(notional=${total_notional:,.2f} / "
        f"max=${max_margin:,.2f})"
    )
    messages.extend(position_lines)

    if utilisation < threshold:
        messages.insert(0,
            f"Margin Utilisation Guard: {utilisation:.1f}% — within limit {threshold:.1f}%."
        )
        return "\n".join(messages)

    breach_msg = (
        f"Margin utilisation {utilisation:.1f}% exceeds threshold {threshold:.1f}% "
        f"— action={action}"
    )

    if dry_run:
        messages.append(f"DRY | {breach_msg}")
    elif action == "alert":
        messages.append(f"ALERT | {breach_msg}")
        for row in rows:
            _log_event(row["id"], "margin_alert", breach_msg)
    elif action == "pause_new":
        # Pause all running deployments that have no open position
        # (prevent new entries while existing ones remain open).
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            flat_rows = conn.execute(
                """
                SELECT id, name FROM deployments
                WHERE status = 'running'
                  AND (open_side IS NULL OR open_qty = 0)
                """
            ).fetchall()
        paused = 0
        for flat_row in flat_rows:
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (flat_row["id"],),
                    )
                _log_event(flat_row["id"], "margin_pause_new", breach_msg)
                paused += 1
            except Exception as e:
                messages.append(
                    f"ERR | {flat_row['name']}: pause failed — {e}"
                )
        messages.append(
            f"PAUSE_NEW | {breach_msg} — paused {paused} flat deployments"
        )

    messages.insert(0,
        f"Margin Utilisation Guard complete — "
        f"utilisation={utilisation:.1f}%, threshold={threshold:.1f}%, "
        f"dry_run={dry_run}"
    )
    return "\n".join(messages)

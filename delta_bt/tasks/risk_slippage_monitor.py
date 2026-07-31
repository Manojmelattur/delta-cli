"""Slippage Monitor Task.

Compares expected fill price (signal price at order time) vs actual
fill price for recent trades. Alerts when average slippage exceeds
a configurable threshold.

Requires deployment_events to contain both:
    - expected_price: the price at signal time
    - fill_price: the actual execution price

Runs every 24 hours (interval_sec=86400).

Kwargs:
    slippage_threshold_bps (float, default 10.0) — Alert threshold in bps.
    lookback_trades        (int,   default 50)   — Number of recent trades.
    dry_run                (bool,  default False).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_SLIPPAGE_THRESHOLD_BPS = 10.0
DEFAULT_LOOKBACK_TRADES        = 50


def _calc_slippage_bps(expected: float, actual: float, side: str) -> float:
    """
    Calculate slippage in basis points.
    Positive = paid more than expected (adverse).
    """
    if expected <= 0:
        return 0.0
    if side.lower() == "long":
        return ((actual - expected) / expected) * 10_000
    else:
        return ((expected - actual) / expected) * 10_000


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
        logger.warning(f"SlippageMonitor: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Slippage Monitor Task.

    Kwargs:
        slippage_threshold_bps (float, default 10.0)
        lookback_trades        (int,   default 50)
        dry_run                (bool,  default False)
    """
    threshold     = float(kwargs.get("slippage_threshold_bps", DEFAULT_SLIPPAGE_THRESHOLD_BPS))
    lookback      = int(kwargs.get("lookback_trades",           DEFAULT_LOOKBACK_TRADES))
    dry_run       = bool(kwargs.get("dry_run",                  False))

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    flagged  = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        deps = conn.execute(
            "SELECT id, name, symbol FROM deployments WHERE status='running'"
        ).fetchall()

    if not deps:
        return "Slippage Monitor: No running deployments found."

    for dep in deps:
        dep_id = dep["id"]
        name   = dep["name"]
        symbol = dep["symbol"]

        with connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT kind, message, ts
                FROM deployment_events
                WHERE deployment_id = ?
                  AND kind IN ('entry', 'exit')
                ORDER BY ts DESC
                LIMIT ?
                """,
                (dep_id, lookback),
            ).fetchall()

        if not rows:
            continue

        slippages = []
        for row in rows:
            try:
                data = json.loads(row["message"] or "{}")
                expected = float(data.get("expected_price", 0))
                actual   = float(data.get("fill_price",     0))
                side     = str(data.get("side", "long"))
                if expected > 0 and actual > 0:
                    slip = _calc_slippage_bps(expected, actual, side)
                    slippages.append(slip)
            except Exception:
                continue

        if not slippages:
            continue

        avg_slip = sum(slippages) / len(slippages)
        max_slip = max(slippages)

        msg = (
            f"{name} ({symbol}): avg_slippage={avg_slip:.2f}bps "
            f"max={max_slip:.2f}bps "
            f"over {len(slippages)} fills "
            f"(threshold={threshold:.1f}bps)"
        )

        if avg_slip > threshold:
            flagged += 1
            if dry_run:
                messages.append(f"DRY | ALERT | {msg}")
            else:
                messages.append(f"ALERT | {msg}")
                _log_event(dep_id, "slippage_alert", msg)
        else:
            messages.append(f"OK  | {msg}")

    summary = (
        f"Slippage Monitor complete — "
        f"deployments_checked={len(deps)}, "
        f"flagged={flagged}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

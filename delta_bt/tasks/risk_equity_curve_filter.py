"""Equity Curve Filter Task.

Monitors each deployment's equity curve against its own moving average.
When equity drops below the MA, position size is halved (defensive mode).
When equity recovers above the MA, full size is restored.

This passively reduces exposure during losing streaks without human
intervention.

Opt-in: set "use_equity_filter": true in a deployment's params_json.
Runs every 4 hours (interval_sec=14400).

Per-deployment overrides (all optional, set in params_json):
    eq_ma_period      (int,   default 20)  — Equity curve MA period (in bars).
    eq_defensive_mult (float, default 0.5) — Size multiplier in defensive mode.
    eq_base_size      (int,   required)    — Full size to restore when above MA.
                                             Defaults to current size if not set.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_MA_PERIOD      = 20
DEFAULT_DEFENSIVE_MULT = 0.5


def _fetch_equity_series(dep_id: int, period: int) -> list:
    """Fetch the most recent `period * 2` equity snapshots."""
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT equity FROM deployment_equity
            WHERE deployment_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (dep_id, period * 2),
        ).fetchall()
    return [float(r["equity"]) for r in reversed(rows)]


def _equity_ma(series: list, period: int) -> Optional[float]:
    if len(series) < period:
        return None
    return sum(series[-period:]) / period


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
        logger.warning(f"EquityCurveFilter: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Equity Curve Filter Task.

    Kwargs:
        eq_ma_period      (int,   default 20)
        eq_defensive_mult (float, default 0.5)
        auto_apply        (bool,  default False)
        dry_run           (bool,  default False)
    """
    global_ma_period      = int(kwargs.get("eq_ma_period",       DEFAULT_MA_PERIOD))
    global_defensive_mult = float(kwargs.get("eq_defensive_mult", DEFAULT_DEFENSIVE_MULT))
    auto_apply            = bool(kwargs.get("auto_apply",          False))
    dry_run               = bool(kwargs.get("dry_run",             False))

    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages  = []
    updated   = 0
    skipped   = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, symbol, size, params_json "
            "FROM deployments WHERE status='running'"
        ).fetchall()

    if not rows:
        return "Equity Curve Filter: No running deployments found."

    for row in rows:
        dep_id   = row["id"]
        name     = row["name"]
        symbol   = row["symbol"]
        cur_size = float(row["size"] or 1)

        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}

        if not params.get("use_equity_filter", False):
            skipped += 1
            continue

        ma_period      = int(params.get("eq_ma_period",       global_ma_period))
        defensive_mult = float(params.get("eq_defensive_mult", global_defensive_mult))
        base_size      = int(params.get("eq_base_size",        cur_size))

        equity_series = _fetch_equity_series(dep_id, ma_period)
        if not equity_series:
            messages.append(
                f"WARN | {name} ({symbol}): no equity history found"
            )
            continue

        ma = _equity_ma(equity_series, ma_period)
        if ma is None:
            messages.append(
                f"WARN | {name} ({symbol}): insufficient equity history "
                f"({len(equity_series)} points, need {ma_period})"
            )
            continue

        current_equity = equity_series[-1]
        below_ma       = current_equity < ma
        defensive_size = max(1, round(base_size * defensive_mult))
        target_size    = defensive_size if below_ma else base_size

        mode = "DEFENSIVE" if below_ma else "NORMAL"
        msg  = (
            f"{name} ({symbol}): mode={mode} "
            f"equity={current_equity:.2f} MA={ma:.2f} "
            f"size {cur_size:.0f} -> {target_size} lots "
            f"(base={base_size} defensive_mult={defensive_mult})"
        )

        if dry_run:
            messages.append(f"DRY | {msg}")
            continue

        if auto_apply and abs(target_size - cur_size) >= 1:
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET size=? WHERE id=?",
                        (target_size, dep_id),
                    )
                updated += 1
                _log_event(dep_id, "equity_filter", f"Size {cur_size:.0f} -> {target_size} | {msg}")
                messages.append(f"OK  | {msg} [Applied]")
            except Exception as e:
                messages.append(f"ERR | {name} ({symbol}): DB write failed — {e}")
        else:
            messages.append(f"INFO | {msg}")

    summary = (
        f"Equity Curve Filter complete — "
        f"updated={updated}, skipped={skipped}, "
        f"auto_apply={auto_apply}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

"""Kelly Criterion Position Sizer Task.

Calculates the optimal position size using the Kelly Criterion based on
historical win rate and average win/loss ratio from closed trades.

Formula:
    kelly_f = win_rate - (1 - win_rate) / (avg_win / avg_loss)
    kelly_f = max(0, min(kelly_f, kelly_cap))
    recommended_size = max(1, round(kelly_f * max_size))

A fractional Kelly (kelly_fraction < 1.0) is applied by default to reduce
variance while preserving most of the growth benefit.

Opt-in: set "use_kelly_sizer": true in a deployment's params_json.
Runs every 24 hours (interval_sec=86400).

Per-deployment overrides (all optional, set in params_json):
    kelly_lookback_trades (int,   default 50)   — Number of recent trades.
    kelly_fraction        (float, default 0.5)  — Fractional Kelly multiplier.
    kelly_max_size        (int,   default 20)   — Max lot size.
    kelly_min_size        (int,   default 1)    — Min lot size.
    kelly_min_trades      (int,   default 20)   — Min trades before applying.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_TRADES = 50
DEFAULT_KELLY_FRACTION  = 0.5
DEFAULT_MAX_SIZE        = 20
DEFAULT_MIN_SIZE        = 1
DEFAULT_MIN_TRADES      = 20


def _calc_kelly(
    trades: list,
    fraction: float,
    max_size: int,
    min_size: int,
) -> tuple[float, float, float, float, int]:
    """
    Calculate Kelly-optimal size from a list of trade PnL values.

    Returns:
        (win_rate, avg_win, avg_loss, kelly_f, recommended_size)
    """
    wins   = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]

    if not wins or not losses:
        return 0.0, 0.0, 0.0, 0.0, min_size

    win_rate = len(wins) / len(trades)
    avg_win  = sum(wins)   / len(wins)
    avg_loss = abs(sum(losses) / len(losses))

    if avg_loss == 0:
        return win_rate, avg_win, avg_loss, 1.0, max_size

    kelly_f = win_rate - (1 - win_rate) / (avg_win / avg_loss)
    kelly_f = max(0.0, min(kelly_f * fraction, 1.0))

    recommended = max(min_size, min(max_size, round(kelly_f * max_size)))
    return win_rate, avg_win, avg_loss, kelly_f, recommended


def _fetch_recent_pnl(dep_id: int, lookback: int) -> list:
    """Fetch PnL values from the most recent N closed trades."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT pnl FROM deployment_events
            WHERE deployment_id = ?
              AND pnl IS NOT NULL
            ORDER BY ts DESC
            LIMIT ?
            """,
            (dep_id, lookback),
        ).fetchall()
    return [float(r[0]) for r in rows]


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
        logger.warning(f"KellySizer: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Kelly Criterion Position Sizer Task.

    Kwargs:
        kelly_lookback_trades (int,   default 50)
        kelly_fraction        (float, default 0.5)
        kelly_max_size        (int,   default 20)
        kelly_min_size        (int,   default 1)
        kelly_min_trades      (int,   default 20)
        auto_apply            (bool,  default False)
        dry_run               (bool,  default False)
    """
    global_lookback   = int(kwargs.get("kelly_lookback_trades", DEFAULT_LOOKBACK_TRADES))
    global_fraction   = float(kwargs.get("kelly_fraction",      DEFAULT_KELLY_FRACTION))
    global_max_size   = int(kwargs.get("kelly_max_size",         DEFAULT_MAX_SIZE))
    global_min_size   = int(kwargs.get("kelly_min_size",         DEFAULT_MIN_SIZE))
    global_min_trades = int(kwargs.get("kelly_min_trades",       DEFAULT_MIN_TRADES))
    auto_apply        = bool(kwargs.get("auto_apply",            False))
    dry_run           = bool(kwargs.get("dry_run",               False))

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    updated  = 0
    skipped  = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, symbol, size, params_json "
            "FROM deployments WHERE status='running'"
        ).fetchall()

    if not rows:
        return "Kelly Sizer: No running deployments found."

    for row in rows:
        dep_id   = row["id"]
        name     = row["name"]
        symbol   = row["symbol"]
        cur_size = float(row["size"] or 1)

        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}

        if not params.get("use_kelly_sizer", False):
            skipped += 1
            continue

        lookback   = int(params.get("kelly_lookback_trades", global_lookback))
        fraction   = float(params.get("kelly_fraction",      global_fraction))
        max_size   = int(params.get("kelly_max_size",         global_max_size))
        min_size   = int(params.get("kelly_min_size",         global_min_size))
        min_trades = int(params.get("kelly_min_trades",       global_min_trades))

        pnl_list = _fetch_recent_pnl(dep_id, lookback)

        if len(pnl_list) < min_trades:
            messages.append(
                f"WARN | {name} ({symbol}): only {len(pnl_list)} trades, "
                f"need {min_trades} — skipping Kelly calculation"
            )
            continue

        win_rate, avg_win, avg_loss, kelly_f, new_size = _calc_kelly(
            pnl_list, fraction, max_size, min_size
        )

        msg = (
            f"{name} ({symbol}): size {cur_size:.0f} -> {new_size} lots "
            f"(trades={len(pnl_list)} "
            f"win_rate={win_rate:.1%} "
            f"avg_win=${avg_win:.2f} "
            f"avg_loss=${avg_loss:.2f} "
            f"kelly_f={kelly_f:.3f} "
            f"fraction={fraction})"
        )

        if dry_run:
            messages.append(f"DRY | {msg}")
            continue

        if auto_apply and abs(new_size - cur_size) >= 1:
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET size=? WHERE id=?",
                        (new_size, dep_id),
                    )
                updated += 1
                _log_event(dep_id, "kelly_sizer", f"Size {cur_size:.0f} -> {new_size} | {msg}")
                messages.append(f"OK  | {msg} [Applied]")
            except Exception as e:
                messages.append(f"ERR | {name} ({symbol}): DB write failed — {e}")
        else:
            messages.append(f"INFO | {msg}")

    summary = (
        f"Kelly Sizer complete — "
        f"updated={updated}, skipped={skipped}, "
        f"auto_apply={auto_apply}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

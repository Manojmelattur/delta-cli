"""Max Drawdown Guard Task.

Monitors portfolio equity across all running deployments and takes
protective action when the drawdown from the equity peak exceeds a
configurable threshold.

Actions (configurable):
    - "pause"  : sets deployment status to 'paused' (no new entries)
    - "close"  : force-closes all open positions via the exchange API
    - "alert"  : logs a warning only, no automated action

Opt-in: all running deployments are monitored by default.
Opt-out: set "skip_drawdown_guard": true in a deployment's params_json.

Runs every 15 minutes (interval_sec=900).

Per-deployment overrides (all optional, set in params_json):
    dd_threshold_pct    (float, default 10.0) — Max allowed drawdown %
    dd_action           (str,   default "pause") — pause | close | alert
    dd_lookback_days    (int,   default 7)    — Equity history window
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Defaults
# -------------------------------------------------------------------
DEFAULT_DD_THRESHOLD_PCT = 10.0
DEFAULT_DD_ACTION        = "pause"
DEFAULT_DD_LOOKBACK_DAYS = 7

_BASE_URLS = {
    "live":    "https://api.india.delta.exchange",
    "testnet": "https://cdn-ind.testnet.deltaex.org",
}
_VENUE_MAP = {
    "paper":         "live",
    "paper_live":    "live",
    "paper_testnet": "testnet",
}


def _client_for_venue(venue: str) -> DeltaClient:
    resolved = _VENUE_MAP.get(venue, venue)
    base_url = _BASE_URLS.get(resolved, _BASE_URLS["live"])
    return DeltaClient(base_url=base_url)


def _calc_drawdown(equity_points: list) -> tuple[float, float, float]:
    """
    Calculate current drawdown from equity peak.

    Returns:
        (peak_equity, current_equity, drawdown_pct)
    """
    if not equity_points:
        return 0.0, 0.0, 0.0
    equities = [float(p["equity"]) for p in equity_points]
    peak     = max(equities)
    current  = equities[-1]
    dd_pct   = ((peak - current) / peak * 100.0) if peak > 0 else 0.0
    return peak, current, dd_pct


def _fetch_equity_history(
    dep_id: int,
    lookback_days: int,
    capital_base: float = 0.0,
) -> list:
    """Reconstruct the per-deployment equity curve from deployment_events.

    There is no dedicated deployment_equity table in this DB; instead the
    scheduler logs realized `pnl` on exit/flip events and unrealized `upnl`
    on tick events.  Equity at each point is:

        capital_base + cumulative_realized_pnl + upnl_at_tick

    capital_base > 0 makes drawdown percentages meaningful (relative to
    account capital) instead of dividing by a near-zero pnl peak.
    """
    since = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat()
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT ts, pnl, upnl
            FROM deployment_events
            WHERE deployment_id = ?
              AND ts > ?
              AND (pnl IS NOT NULL OR upnl IS NOT NULL)
            ORDER BY ts ASC
            """,
            (dep_id, since),
        ).fetchall()

    points = []
    cum_realized = 0.0
    for r in rows:
        if r["pnl"] is not None:
            cum_realized += float(r["pnl"])
        upnl = float(r["upnl"]) if r["upnl"] is not None else 0.0
        points.append(
            {"ts": r["ts"], "equity": capital_base + cum_realized + upnl}
        )
    return points


def _pause_deployment(dep_id: int, reason: str) -> None:
    """Set deployment status to paused."""
    with connect() as conn:
        conn.execute(
            "UPDATE deployments SET status='paused' WHERE id=?",
            (dep_id,),
        )


def _close_position(
    venue: str,
    symbol: str,
    open_side: str,
    open_qty: float,
) -> Optional[str]:
    """
    Submit a market order to close the open position via the exchange API.
    Returns an error string on failure, None on success.
    """
    try:
        client     = _client_for_venue(venue)
        close_side = "sell" if open_side.lower() == "long" else "buy"
        client.place_order(           
            side=close_side,
            size=int(open_qty),
            order_type="market_order",
            product_id=27
        )
        return None
    except Exception as e:
        return str(e)


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
        logger.warning(f"MaxDrawdownGuard: event log failed: {e}")


# -------------------------------------------------------------------
# Main task entry point
# -------------------------------------------------------------------

def run(**kwargs) -> str:
    """
    Max Drawdown Guard Task.

    Kwargs:
        dd_threshold_pct (float, default 10.0) — Global drawdown threshold %.
        dd_action        (str,   default "pause") — Global action: pause|close|alert.
        dd_lookback_days (int,   default 7)     — Equity history window in days.
        dry_run          (bool,  default False) — Log actions without executing.
    """
    global_threshold  = float(kwargs.get("dd_threshold_pct", DEFAULT_DD_THRESHOLD_PCT))
    global_action     = str(kwargs.get("dd_action",          DEFAULT_DD_ACTION))
    global_lookback   = int(kwargs.get("dd_lookback_days",   DEFAULT_DD_LOOKBACK_DAYS))
    dry_run           = bool(kwargs.get("dry_run",           False))
    capital_base      = float(kwargs.get("dd_capital_base_usd", 0.0))

    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages  = []
    triggered = 0
    monitored = 0
    skipped   = 0

    # --- Load all running deployments ---
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, venue, params_json,
                   open_side, open_qty, open_price
            FROM deployments
            WHERE status = 'running'
            """
        ).fetchall()

    if not rows:
        return "Max Drawdown Guard: No running deployments found."

    for row in rows:
        dep_id    = row["id"]
        name      = row["name"]
        symbol    = row["symbol"]
        venue     = row["venue"]
        open_side = row["open_side"]
        open_qty  = float(row["open_qty"] or 0)

        # --- Parse per-deployment overrides ---
        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}

        if params.get("skip_drawdown_guard", False):
            skipped += 1
            continue

        threshold  = float(params.get("dd_threshold_pct", global_threshold))
        action     = str(params.get("dd_action",          global_action))
        lookback   = int(params.get("dd_lookback_days",   global_lookback))

        if action not in ("pause", "close", "alert"):
            action = "pause"

        # --- Fetch equity history ---
        equity_history = _fetch_equity_history(dep_id, lookback, capital_base)
        if len(equity_history) < 2:
            messages.append(
                f"WARN | {name} ({symbol}): insufficient equity history "
                f"({len(equity_history)} points) — skipping"
            )
            continue

        monitored += 1
        peak, current, dd_pct = _calc_drawdown(equity_history)

        if dd_pct < threshold:
            continue

        # --- Threshold breached ---
        triggered += 1
        breach_msg = (
            f"Drawdown {dd_pct:.2f}% exceeds threshold {threshold:.2f}% "
            f"(peak={peak:.2f}, current={current:.2f}) — action={action}"
        )

        if dry_run:
            messages.append(f"DRY | {name} ({symbol}): {breach_msg}")
            continue

        if action == "alert":
            messages.append(f"ALERT | {name} ({symbol}): {breach_msg}")
            _log_event(dep_id, "dd_alert", breach_msg)

        elif action == "pause":
            try:
                _pause_deployment(dep_id, breach_msg)
                messages.append(f"PAUSE | {name} ({symbol}): {breach_msg}")
                _log_event(dep_id, "dd_pause", breach_msg)
            except Exception as e:
                messages.append(
                    f"ERR | {name} ({symbol}): pause failed — {e}"
                )

        elif action == "close":
            if open_side and open_qty > 0:
                err = _close_position(venue, symbol, open_side, open_qty)
                if err:
                    messages.append(
                        f"ERR | {name} ({symbol}): close failed — {err}"
                    )
                    _log_event(dep_id, "dd_close_failed", f"{breach_msg} | err={err}")
                else:
                    # Also pause to prevent re-entry.
                    try:
                        _pause_deployment(dep_id, breach_msg)
                    except Exception:
                        pass
                    messages.append(f"CLOSE | {name} ({symbol}): {breach_msg}")
                    _log_event(dep_id, "dd_close", breach_msg)
            else:
                # No open position — just pause.
                try:
                    _pause_deployment(dep_id, breach_msg)
                    messages.append(
                        f"PAUSE | {name} ({symbol}): {breach_msg} (no open position)"
                    )
                    _log_event(dep_id, "dd_pause", breach_msg)
                except Exception as e:
                    messages.append(
                        f"ERR | {name} ({symbol}): pause failed — {e}"
                    )

    summary = (
        f"Max Drawdown Guard complete — "
        f"monitored={monitored}, triggered={triggered}, "
        f"skipped={skipped}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

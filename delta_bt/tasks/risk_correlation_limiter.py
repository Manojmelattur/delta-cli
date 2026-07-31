"""Correlation Limiter Task.

Prevents simultaneously holding positions in highly correlated symbols.
When two or more open positions exceed the correlation threshold, the
newer position is closed (or flagged) to reduce directional overlap.

Correlation is computed from recent close-price returns using a
configurable lookback window.

Runs every 30 minutes (interval_sec=1800).

Opt-out: set "skip_correlation_limiter": true in a deployment's params_json.

Kwargs:
    correlation_threshold (float, default 0.85) — Pearson r above which
                                                   two symbols are considered
                                                   correlated.
    lookback_days         (int,   default 14)   — Days of price history for
                                                   correlation calculation.
    action                (str,   default "alert") — alert | close.
    dry_run               (bool,  default False).
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_CORRELATION_THRESHOLD = 0.85
DEFAULT_LOOKBACK_DAYS         = 14
DEFAULT_ACTION                = "alert"

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


def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    """Compute Pearson correlation coefficient between two return series."""
    n = min(len(x), len(y))
    if n < 10:
        return None
    x, y = x[-n:], y[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    num   = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    den_x = math.sqrt(sum((v - mx) ** 2 for v in x))
    den_y = math.sqrt(sum((v - my) ** 2 for v in y))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _fetch_returns(
    symbol: str,
    venue: str,
    lookback_days: int,
) -> Optional[List[float]]:
    """Fetch daily close-price returns for a symbol."""
    try:
        client   = _client_for_venue(venue)
        end_time = datetime.now(timezone.utc)
        start    = end_time - timedelta(days=lookback_days + 2)
        candles  = client.candles(symbol, "1d", start, end_time)
        if not candles or len(candles) < 5:
            return None
        closes  = [float(c["close"]) for c in candles]
        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] != 0
        ]
        return returns
    except Exception as e:
        logger.warning(f"CorrelationLimiter: failed to fetch returns for {symbol}: {e}")
        return None


def _close_position(
    venue: str,
    symbol: str,
    open_side: str,
    open_qty: float,
) -> str | None:
    try:
        client     = _client_for_venue(venue)
        close_side = "sell" if open_side.lower() == "long" else "buy"
        client.place_order(
            product_id=27,
            side=close_side,
            size=int(open_qty),
            order_type="market_order",
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
        logger.warning(f"CorrelationLimiter: event log failed: {e}")


# -------------------------------------------------------------------
# Main task entry point
# -------------------------------------------------------------------

def run(**kwargs) -> str:
    """
    Correlation Limiter Task.

    Kwargs:
        correlation_threshold (float, default 0.85)
        lookback_days         (int,   default 14)
        action                (str,   default "alert") — alert | close
        dry_run               (bool,  default False)
    """
    threshold     = float(kwargs.get("correlation_threshold", DEFAULT_CORRELATION_THRESHOLD))
    lookback_days = int(kwargs.get("lookback_days",           DEFAULT_LOOKBACK_DAYS))
    action        = str(kwargs.get("action",                  DEFAULT_ACTION))
    dry_run       = bool(kwargs.get("dry_run",                False))

    if action not in ("alert", "close"):
        action = "alert"

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    pairs_checked  = 0
    pairs_flagged  = 0

    # --- Load all running deployments with open positions ---
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, venue, params_json,
                   open_side, open_qty, open_price,
                   strftime('%s', opened_at) AS opened_ts
            FROM deployments
            WHERE status = 'running'
              AND open_side IS NOT NULL
              AND open_qty  > 0
            """
        ).fetchall()

    if len(rows) < 2:
        return (
            "Correlation Limiter: fewer than 2 open positions — "
            "no correlation check needed."
        )

    # Filter out opted-out deployments.
    active = []
    for row in rows:
        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}
        if not params.get("skip_correlation_limiter", False):
            active.append(row)

    if len(active) < 2:
        return "Correlation Limiter: fewer than 2 eligible open positions."

    # --- Fetch returns for all unique symbols ---
    returns_cache: Dict[str, Optional[List[float]]] = {}
    for row in active:
        sym = row["symbol"]
        if sym not in returns_cache:
            returns_cache[sym] = _fetch_returns(sym, row["venue"], lookback_days)

    # --- Check all pairs ---
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a = active[i]
            b = active[j]

            # Only flag same-direction positions — opposite sides hedge.
            if a["open_side"] != b["open_side"]:
                continue

            ret_a = returns_cache.get(a["symbol"])
            ret_b = returns_cache.get(b["symbol"])
            if ret_a is None or ret_b is None:
                continue

            pairs_checked += 1
            corr = _pearson(ret_a, ret_b)
            if corr is None or corr < threshold:
                continue

            pairs_flagged += 1

            # The newer position is the one to act on.
            ts_a = int(a["opened_ts"] or 0)
            ts_b = int(b["opened_ts"] or 0)
            newer = b if ts_b >= ts_a else a

            flag_msg = (
                f"Correlated pair: {a['name']} ({a['symbol']}) + "
                f"{b['name']} ({b['symbol']}) "
                f"r={corr:.3f} >= {threshold} "
                f"side={a['open_side']} — "
                f"newer={newer['name']} ({newer['symbol']})"
            )

            if dry_run:
                messages.append(f"DRY | {flag_msg}")
                continue

            if action == "alert":
                messages.append(f"ALERT | {flag_msg}")
                _log_event(newer["id"], "correlation_alert", flag_msg)

            elif action == "close":
                err = _close_position(
                    newer["venue"],
                    newer["symbol"],
                    newer["open_side"],
                    float(newer["open_qty"]),
                )
                if err:
                    messages.append(
                        f"ERR | {newer['name']} ({newer['symbol']}): "
                        f"close failed — {err} | {flag_msg}"
                    )
                    _log_event(
                        newer["id"], "correlation_close_failed",
                        f"{flag_msg} | err={err}",
                    )
                else:
                    messages.append(f"CLOSE | {newer['name']} ({newer['symbol']}): {flag_msg}")
                    _log_event(newer["id"], "correlation_close", flag_msg)

    summary = (
        f"Correlation Limiter complete — "
        f"open_positions={len(active)}, "
        f"pairs_checked={pairs_checked}, "
        f"pairs_flagged={pairs_flagged}, "
        f"dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

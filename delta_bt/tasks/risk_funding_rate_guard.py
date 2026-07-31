"""Funding Rate Guard Task.

Monitors perpetual funding rates for all running deployments.
When funding becomes excessively adverse for an open position,
the task alerts or closes the position to prevent funding costs
from eroding profitability.

Adverse funding:
    LONG  position + positive funding rate = paying funding (cost)
    SHORT position + negative funding rate = paying funding (cost)

Runs every 1 hour (interval_sec=3600).

Kwargs:
    funding_threshold_pct (float, default 0.1)  — Annualised funding rate %
                                                   above which action is taken.
    action                (str,   default "alert") — alert | close.
    dry_run               (bool,  default False).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_FUNDING_THRESHOLD_PCT = 0.1

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


def _get_product_id(client: DeltaClient, symbol: str) -> int:
    try:
        prod = client.get_product(symbol)
        return int(prod.get("id") or 0)
    except Exception:
        return 0


def _get_funding_rate(client: DeltaClient, symbol: str) -> float | None:
    """Fetch current funding rate for a perpetual symbol."""
    try:
        data = client.ticker(symbol)
        rate = data.get("funding_rate")
        return float(rate) if rate is not None else None
    except Exception as e:
        logger.warning(f"FundingGuard: failed to fetch funding for {symbol}: {e}")
        return None



def _close_position(
    venue: str,
    symbol: str,
    open_side: str,
    open_qty: float,
) -> str | None:
    try:
        client     = _client_for_venue(venue)
        product_id = _get_product_id(client, symbol)
        if not product_id:
            return f"Could not resolve product_id for {symbol}"
        close_side = "sell" if open_side.lower() == "long" else "buy"
        client.place_order(
            side=close_side,
            size=int(open_qty),
            order_type="market_order",
            product_id=product_id,
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
        logger.warning(f"FundingGuard: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Funding Rate Guard Task.

    Kwargs:
        funding_threshold_pct (float, default 0.1)
        action                (str,   default "alert") — alert | close
        dry_run               (bool,  default False)
    """
    threshold = float(kwargs.get("funding_threshold_pct", DEFAULT_FUNDING_THRESHOLD_PCT))
    action    = str(kwargs.get("action",                  "alert"))
    dry_run   = bool(kwargs.get("dry_run",                False))

    if action not in ("alert", "close"):
        action = "alert"

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    flagged  = 0
    checked  = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, venue,
                   open_side, open_qty
            FROM deployments
            WHERE status   = 'running'
              AND open_side IS NOT NULL
              AND open_qty  > 0
            """
        ).fetchall()

    if not rows:
        return "Funding Rate Guard: No open positions found."

    for row in rows:
        dep_id    = row["id"]
        name      = row["name"]
        symbol    = row["symbol"]
        venue     = row["venue"]
        open_side = row["open_side"]
        open_qty  = float(row["open_qty"])

        client      = _client_for_venue(venue)
        funding_rate = _get_funding_rate(client, symbol)

        if funding_rate is None:
            messages.append(
                f"WARN | {name} ({symbol}): could not fetch funding rate"
            )
            continue

        checked += 1

        # Determine if funding is adverse for this position.
        is_long  = open_side.lower() == "long"
        adverse  = (is_long and funding_rate > 0) or \
                   (not is_long and funding_rate < 0)
        abs_rate = abs(funding_rate)

        if not adverse or abs_rate < threshold:
            messages.append(
                f"OK  | {name} ({symbol}): funding={funding_rate:.4f}% "
                f"side={open_side} — not adverse"
            )
            continue

        flagged += 1
        flag_msg = (
            f"Adverse funding: {name} ({symbol}) "
            f"funding={funding_rate:.4f}% "
            f"side={open_side} qty={open_qty:.0f} "
            f"threshold={threshold:.4f}% — action={action}"
        )

        if dry_run:
            messages.append(f"DRY | {flag_msg}")
            continue

        if action == "alert":
            messages.append(f"ALERT | {flag_msg}")
            _log_event(dep_id, "funding_alert", flag_msg)

        elif action == "close":
            err = _close_position(venue, symbol, open_side, open_qty)
            if err:
                messages.append(
                    f"ERR | {name} ({symbol}): close failed — {err}"
                )
                _log_event(dep_id, "funding_close_failed",
                           f"{flag_msg} | err={err}")
            else:
                messages.append(f"CLOSE | {flag_msg}")
                _log_event(dep_id, "funding_close", flag_msg)

    summary = (
        f"Funding Rate Guard complete — "
        f"checked={checked}, flagged={flagged}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

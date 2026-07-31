"""Max Open Positions Guard Task.

Caps the total number of simultaneously open positions across all
running deployments. When the cap is exceeded, the newest positions
are closed until the count is within the limit.

Runs every 15 minutes (interval_sec=900).

Kwargs:
    max_positions (int,  default 3)       — Global max open positions.
    action        (str,  default "alert") — alert | close.
    dry_run       (bool, default False).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_MAX_POSITIONS = 3

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
        logger.warning(f"MaxOpenPositions: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Max Open Positions Guard Task.

    Kwargs:
        max_positions (int,  default 3)
        action        (str,  default "alert") — alert | close
        dry_run       (bool, default False)
    """
    max_positions = int(kwargs.get("max_positions", DEFAULT_MAX_POSITIONS))
    action        = str(kwargs.get("action",        "alert"))
    dry_run       = bool(kwargs.get("dry_run",       False))

    if action not in ("alert", "close"):
        action = "alert"

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, venue,
                   open_side, open_qty, opened_at
            FROM deployments
            WHERE status   = 'running'
              AND open_side IS NOT NULL
              AND open_qty  > 0
            ORDER BY opened_at ASC
            """
        ).fetchall()

    open_count = len(rows)

    if open_count <= max_positions:
        return (
            f"Max Open Positions: {open_count}/{max_positions} open — "
            f"within limit."
        )

    excess   = open_count - max_positions
    # Close newest positions first (rows sorted oldest-first, so reverse).
    to_close = list(reversed(rows))[:excess]

    for row in to_close:
        dep_id    = row["id"]
        name      = row["name"]
        symbol    = row["symbol"]
        venue     = row["venue"]
        open_side = row["open_side"]
        open_qty  = float(row["open_qty"])

        flag_msg = (
            f"Open positions {open_count} exceeds max {max_positions} — "
            f"closing newest: {name} ({symbol} {open_side} {open_qty:.0f})"
        )

        if dry_run:
            messages.append(f"DRY | {flag_msg}")
            continue

        if action == "alert":
            messages.append(f"ALERT | {flag_msg}")
            _log_event(dep_id, "max_positions_alert", flag_msg)

        elif action == "close":
            err = _close_position(venue, symbol, open_side, open_qty)
            if err:
                messages.append(
                    f"ERR | {name} ({symbol}): close failed — {err}"
                )
                _log_event(dep_id, "max_positions_close_failed",
                           f"{flag_msg} | err={err}")
            else:
                messages.append(f"CLOSE | {name} ({symbol}): {flag_msg}")
                _log_event(dep_id, "max_positions_close", flag_msg)

    summary = (
        f"Max Open Positions complete — "
        f"open={open_count}, max={max_positions}, "
        f"excess={excess}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

"""Sector Exposure Cap Task.

Limits total notional exposure per asset sector. Sectors are defined
in a configurable mapping. When a sector's total notional exceeds its
cap, the largest position in that sector is flagged or closed.

Sector mapping is provided via kwargs or falls back to a built-in
default grouping for common Delta Exchange symbols.

Runs every 30 minutes (interval_sec=1800).

Kwargs:
    sector_caps    (dict)  — {"DeFi": 5000, "L1": 10000, ...} in USD.
    sector_map     (dict)  — {"SOLUSD": "L1", "ETHUSD": "L1", ...}.
    action         (str,   default "alert") — alert | close.
    dry_run        (bool,  default False).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

# Default sector groupings for common Delta Exchange perpetuals.
_DEFAULT_SECTOR_MAP: Dict[str, str] = {
    "BTCUSD":  "L1",
    "ETHUSD":  "L1",
    "SOLUSD":  "L1",
    "BNBUSD":  "L1",
    "AVAXUSD": "L1",
    "ADAUSD":  "L1",
    "DOTUSD":  "L1",
    "MATICUSD":"L2",
    "ARBUSD":  "L2",
    "OPUSD":   "L2",
    "UNIUSD":  "DeFi",
    "AAVEUSD": "DeFi",
    "CRVUSD":  "DeFi",
    "LINKUSD": "Oracle",
    "DOGEUSD": "Meme",
    "SHIBUSD": "Meme",
}

_DEFAULT_SECTOR_CAPS: Dict[str, float] = {
    "L1":     20_000.0,
    "L2":     10_000.0,
    "DeFi":    5_000.0,
    "Oracle":  5_000.0,
    "Meme":    3_000.0,
}

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
        logger.warning(f"SectorExposureCap: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Sector Exposure Cap Task.

    Kwargs:
        sector_caps (dict)  — Per-sector USD notional caps.
        sector_map  (dict)  — Symbol-to-sector mapping.
        action      (str,   default "alert") — alert | close.
        dry_run     (bool,  default False).
    """
    sector_caps = kwargs.get("sector_caps", _DEFAULT_SECTOR_CAPS)
    sector_map  = kwargs.get("sector_map",  _DEFAULT_SECTOR_MAP)
    action      = str(kwargs.get("action",  "alert"))
    dry_run     = bool(kwargs.get("dry_run", False))

    if action not in ("alert", "close"):
        action = "alert"

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    flagged  = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, venue,
                   open_side, open_qty, open_price
            FROM deployments
            WHERE status   = 'running'
              AND open_side IS NOT NULL
              AND open_qty  > 0
            """
        ).fetchall()

    if not rows:
        return "Sector Exposure Cap: No open positions found."

    # Group positions by sector.
    sector_positions: Dict[str, List] = {}
    unmapped = []
    for row in rows:
        sector = sector_map.get(row["symbol"])
        if not sector:
            unmapped.append(row["symbol"])
            continue
        sector_positions.setdefault(sector, []).append(row)

    if unmapped:
        messages.append(
            f"INFO | Unmapped symbols (no sector assigned): "
            f"{', '.join(set(unmapped))}"
        )

    for sector, positions in sector_positions.items():
        cap = sector_caps.get(sector)
        if cap is None:
            continue

        # Calculate total notional for this sector.
        total_notional = sum(
            float(p["open_qty"]) * float(p["open_price"] or 0)
            for p in positions
        )

        if total_notional <= cap:
            continue

        flagged += 1
        excess = total_notional - cap

        # Sort by notional descending — close largest first.
        positions_sorted = sorted(
            positions,
            key=lambda p: float(p["open_qty"]) * float(p["open_price"] or 0),
            reverse=True,
        )

        flag_msg = (
            f"Sector '{sector}': notional ${total_notional:,.2f} "
            f"exceeds cap ${cap:,.2f} (excess=${excess:,.2f})"
        )
        messages.append(f"WARN | {flag_msg}")

        for pos in positions_sorted:
            dep_id    = pos["id"]
            name      = pos["name"]
            symbol    = pos["symbol"]
            venue     = pos["venue"]
            open_side = pos["open_side"]
            open_qty  = float(pos["open_qty"])
            notional  = open_qty * float(pos["open_price"] or 0)

            pos_msg = (
                f"{name} ({symbol}): notional=${notional:,.2f} "
                f"qty={open_qty:.0f} side={open_side}"
            )

            if dry_run:
                messages.append(f"DRY | {pos_msg}")
                break

            if action == "alert":
                messages.append(f"ALERT | {pos_msg}")
                _log_event(dep_id, "sector_cap_alert",
                           f"{flag_msg} | {pos_msg}")
                break  # alert once per sector

            elif action == "close":
                err = _close_position(venue, symbol, open_side, open_qty)
                if err:
                    messages.append(
                        f"ERR | {name} ({symbol}): close failed — {err}"
                    )
                    _log_event(dep_id, "sector_cap_close_failed",
                               f"{flag_msg} | {pos_msg} | err={err}")
                else:
                    messages.append(f"CLOSE | {pos_msg}")
                    _log_event(dep_id, "sector_cap_close",
                               f"{flag_msg} | {pos_msg}")
                    break  # close one at a time, re-check on next run

    summary = (
        f"Sector Exposure Cap complete — "
        f"sectors_checked={len(sector_positions)}, "
        f"sectors_flagged={flagged}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

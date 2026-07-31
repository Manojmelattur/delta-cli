"""Liquidity Guard Task.

Checks 24-hour trading volume before allowing new entries. Pauses
deployments on illiquid symbols where slippage would be excessive.

A symbol is considered illiquid when its 24h volume (in USD) is below
the configured threshold.

Runs every 4 hours (interval_sec=14400).

Kwargs:
    min_volume_usd   (float, default 1_000_000) — Min 24h USD volume.
    action           (str,   default "alert")   — alert | pause.
    dry_run          (bool,  default False).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_MIN_VOLUME_USD = 1_000_000.0

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


def _get_24h_volume(client: DeltaClient, symbol: str) -> float | None:
    """Fetch 24h USD turnover from the ticker."""
    try:
        data = client.ticker(symbol)
        vol  = data.get("turnover_usd") or data.get("volume")
        return float(vol) if vol is not None else None
    except Exception as e:
        logger.warning(f"LiquidityGuard: failed to fetch volume for {symbol}: {e}")
        return None



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
        logger.warning(f"LiquidityGuard: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Liquidity Guard Task.

    Kwargs:
        min_volume_usd (float, default 1_000_000)
        action         (str,   default "alert") — alert | pause
        dry_run        (bool,  default False)
    """
    min_volume = float(kwargs.get("min_volume_usd", DEFAULT_MIN_VOLUME_USD))
    action     = str(kwargs.get("action",           "alert"))
    dry_run    = bool(kwargs.get("dry_run",          False))

    if action not in ("alert", "pause"):
        action = "alert"

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    flagged  = 0
    checked  = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, symbol, venue "
            "FROM deployments WHERE status='running'"
        ).fetchall()

    if not rows:
        return "Liquidity Guard: No running deployments found."

    # Deduplicate symbols to avoid redundant API calls.
    seen: dict = {}
    for row in rows:
        key = (row["symbol"], row["venue"])
        if key not in seen:
            client = _client_for_venue(row["venue"])
            vol    = _get_24h_volume(client, row["symbol"])
            seen[key] = vol

    for row in rows:
        dep_id = row["id"]
        name   = row["name"]
        symbol = row["symbol"]
        venue  = row["venue"]

        vol = seen.get((symbol, venue))
        if vol is None:
            messages.append(
                f"WARN | {name} ({symbol}): could not fetch 24h volume"
            )
            continue

        checked += 1
        msg = (
            f"{name} ({symbol}): 24h_volume=${vol:,.0f} "
            f"(min=${min_volume:,.0f})"
        )

        if vol >= min_volume:
            messages.append(f"OK  | {msg}")
            continue

        flagged += 1
        flag_msg = f"Illiquid: {msg} — action={action}"

        if dry_run:
            messages.append(f"DRY | {flag_msg}")
            continue

        if action == "alert":
            messages.append(f"ALERT | {flag_msg}")
            _log_event(dep_id, "liquidity_alert", flag_msg)

        elif action == "pause":
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (dep_id,),
                    )
                messages.append(f"PAUSE | {flag_msg}")
                _log_event(dep_id, "liquidity_pause", flag_msg)
            except Exception as e:
                messages.append(
                    f"ERR | {name} ({symbol}): pause failed — {e}"
                )

    summary = (
        f"Liquidity Guard complete — "
        f"checked={checked}, flagged={flagged}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

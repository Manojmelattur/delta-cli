"""Position Age Timeout Task.

Force-closes any open position that has been held longer than the
configured maximum age without hitting its SL or TP. Eliminates
zombie trades that are stuck and tying up capital.

Opt-out: set "skip_age_timeout": true in a deployment's params_json.

Runs every 30 minutes (interval_sec=1800).

Per-deployment overrides (all optional, set in params_json):
    max_position_age_hours (float, default 48.0) — Max hours before force-close.
    age_action             (str,   default "close") — close | alert.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_HOURS = 48.0
DEFAULT_AGE_ACTION    = "close"

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
        logger.warning(f"PositionAgeTimeout: event log failed: {e}")


# -------------------------------------------------------------------
# Main task entry point
# -------------------------------------------------------------------

def run(**kwargs) -> str:
    """
    Position Age Timeout Task.

    Kwargs:
        max_position_age_hours (float, default 48.0)
        age_action             (str,   default "close") — close | alert
        dry_run                (bool,  default False)
    """
    global_max_age = float(kwargs.get("max_position_age_hours", DEFAULT_MAX_AGE_HOURS))
    global_action  = str(kwargs.get("age_action",               DEFAULT_AGE_ACTION))
    dry_run        = bool(kwargs.get("dry_run",                  False))

    if global_action not in ("close", "alert"):
        global_action = "close"

    now        = datetime.now(timezone.utc)
    now_str    = now.strftime("%Y-%m-%d %H:%M UTC")
    messages   = []
    checked    = 0
    triggered  = 0
    skipped    = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, venue, params_json,
                   open_side, open_qty, open_price, opened_at
            FROM deployments
            WHERE status  = 'running'
              AND open_side IS NOT NULL
              AND open_qty  > 0
              AND opened_at IS NOT NULL
            """
        ).fetchall()

    if not rows:
        return "Position Age Timeout: No open positions found."

    for row in rows:
        dep_id    = row["id"]
        name      = row["name"]
        symbol    = row["symbol"]
        venue     = row["venue"]
        open_side = row["open_side"]
        open_qty  = float(row["open_qty"])
        opened_at = row["opened_at"]

        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}

        if params.get("skip_age_timeout", False):
            skipped += 1
            continue

        max_age_hours = float(params.get("max_position_age_hours", global_max_age))
        action        = str(params.get("age_action",               global_action))
        if action not in ("close", "alert"):
            action = "close"

        # Parse opened_at timestamp.
        try:
            opened_dt = datetime.fromisoformat(
                opened_at.replace("Z", "+00:00")
            )
        except Exception:
            messages.append(
                f"WARN | {name} ({symbol}): cannot parse opened_at='{opened_at}'"
            )
            continue

        checked += 1
        age_hours = (now - opened_dt).total_seconds() / 3600.0

        if age_hours < max_age_hours:
            continue

        triggered += 1
        age_msg = (
            f"Position age {age_hours:.1f}h exceeds limit {max_age_hours:.1f}h "
            f"(opened={opened_at}, side={open_side}, qty={open_qty:.4f}) "
            f"— action={action}"
        )

        if dry_run:
            messages.append(f"DRY | {name} ({symbol}): {age_msg}")
            continue

        if action == "alert":
            messages.append(f"ALERT | {name} ({symbol}): {age_msg}")
            _log_event(dep_id, "age_timeout_alert", age_msg)

        elif action == "close":
            err = _close_position(venue, symbol, open_side, open_qty)
            if err:
                messages.append(
                    f"ERR | {name} ({symbol}): close failed — {err}"
                )
                _log_event(
                    dep_id, "age_timeout_close_failed",
                    f"{age_msg} | err={err}",
                )
            else:
                messages.append(f"CLOSE | {name} ({symbol}): {age_msg}")
                _log_event(dep_id, "age_timeout_close", age_msg)

    summary = (
        f"Position Age Timeout complete — "
        f"checked={checked}, triggered={triggered}, "
        f"skipped={skipped}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

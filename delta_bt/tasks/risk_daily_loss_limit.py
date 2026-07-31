"""Daily Loss Limit Task.

Monitors realised PnL for each running deployment within the current
UTC trading day. When cumulative daily loss exceeds the configured
threshold, the deployment is paused and any open position is closed.

Resets automatically at UTC midnight — no manual intervention needed.

Opt-out: set "skip_daily_loss_limit": true in a deployment's params_json.

Runs every 15 minutes (interval_sec=900).

Per-deployment overrides (all optional, set in params_json):
    daily_loss_limit_usd   (float, default -200.0) — Max daily loss in USD.
                                                      Must be negative.
    daily_loss_action      (str,   default "pause") — pause | close | alert.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_DAILY_LOSS_LIMIT_USD = -200.0
DEFAULT_DAILY_LOSS_ACTION    = "pause"

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


def _today_start_utc() -> str:
    """Return ISO timestamp for the start of today in UTC."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"


def _fetch_daily_pnl(dep_id: int) -> float:
    """Sum all realised PnL for a deployment since UTC midnight."""
    since = _today_start_utc()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS daily_pnl
            FROM deployment_events
            WHERE deployment_id = ?
              AND ts >= ?
              AND pnl IS NOT NULL
            """,
            (dep_id, since),
        ).fetchone()
    return float(row[0]) if row else 0.0


def _pause_deployment(dep_id: int) -> None:
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
        logger.warning(f"DailyLossLimit: event log failed: {e}")


# -------------------------------------------------------------------
# Main task entry point
# -------------------------------------------------------------------

def run(**kwargs) -> str:
    """
    Daily Loss Limit Task.

    Kwargs:
        daily_loss_limit_usd (float, default -200.0) — Global daily loss cap.
        daily_loss_action    (str,   default "pause") — pause | close | alert.
        dry_run              (bool,  default False)   — Log without acting.
    """
    global_limit  = float(kwargs.get("daily_loss_limit_usd", DEFAULT_DAILY_LOSS_LIMIT_USD))
    global_action = str(kwargs.get("daily_loss_action",      DEFAULT_DAILY_LOSS_ACTION))
    dry_run       = bool(kwargs.get("dry_run",               False))

    # Ensure limit is negative.
    if global_limit > 0:
        global_limit = -global_limit

    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    today     = _today_start_utc()[:10]
    messages  = []
    triggered = 0
    monitored = 0
    skipped   = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, symbol, venue, params_json,
                   open_side, open_qty
            FROM deployments
            WHERE status = 'running'
            """
        ).fetchall()

    if not rows:
        return "Daily Loss Limit: No running deployments found."

    for row in rows:
        dep_id    = row["id"]
        name      = row["name"]
        symbol    = row["symbol"]
        venue     = row["venue"]
        open_side = row["open_side"]
        open_qty  = float(row["open_qty"] or 0)

        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}

        if params.get("skip_daily_loss_limit", False):
            skipped += 1
            continue

        limit  = float(params.get("daily_loss_limit_usd", global_limit))
        action = str(params.get("daily_loss_action",      global_action))

        # Ensure limit is negative.
        if limit > 0:
            limit = -limit
        if action not in ("pause", "close", "alert"):
            action = "pause"

        monitored += 1
        daily_pnl = _fetch_daily_pnl(dep_id)

        if daily_pnl >= limit:
            continue

        # --- Limit breached ---
        triggered += 1
        breach_msg = (
            f"Daily loss ${daily_pnl:.2f} exceeds limit ${limit:.2f} "
            f"(date={today}) — action={action}"
        )

        if dry_run:
            messages.append(f"DRY | {name} ({symbol}): {breach_msg}")
            continue

        if action == "alert":
            messages.append(f"ALERT | {name} ({symbol}): {breach_msg}")
            _log_event(dep_id, "daily_loss_alert", breach_msg)

        elif action in ("pause", "close"):
            # Close position first if open.
            if action == "close" and open_side and open_qty > 0:
                err = _close_position(venue, symbol, open_side, open_qty)
                if err:
                    messages.append(
                        f"ERR | {name} ({symbol}): close failed — {err}"
                    )
                    _log_event(
                        dep_id, "daily_loss_close_failed",
                        f"{breach_msg} | err={err}",
                    )
                    continue
                _log_event(dep_id, "daily_loss_close", breach_msg)

            # Pause deployment.
            try:
                _pause_deployment(dep_id)
                messages.append(f"PAUSE | {name} ({symbol}): {breach_msg}")
                _log_event(dep_id, "daily_loss_pause", breach_msg)
            except Exception as e:
                messages.append(
                    f"ERR | {name} ({symbol}): pause failed — {e}"
                )

    summary = (
        f"Daily Loss Limit complete — "
        f"monitored={monitored}, triggered={triggered}, "
        f"skipped={skipped}, dry_run={dry_run}, date={today}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

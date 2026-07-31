import json
import os
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


# Fix 7: correct base URL via env var
_BASE_URL = os.getenv("DELTA_LIVE_BASE_URL", "https://api.india.delta.exchange")

# Cache contract values per symbol to avoid repeated API calls
_CV_CACHE: dict = {}


def _get_contract_value(client: DeltaClient, symbol: str) -> float:
    """Fetch contract value from Delta API with in-memory cache."""
    if symbol in _CV_CACHE:
        return _CV_CACHE[symbol]
    try:
        prod = client.get_product(symbol)
        cv   = float(prod.get("contract_value") or 1) or 1.0
    except Exception:
        cv = 1.0
    _CV_CACHE[symbol] = cv
    return cv


def run(**kwargs):
    limit       = float(kwargs.get("max_exposure_usd", 10000.0))
    # Fix 4: auto-resume flat bots when exposure drops back within limits
    auto_resume = bool(kwargs.get("auto_resume", True))

    # Fix 2: instantiate DeltaClient to fetch contract values per symbol
    client = DeltaClient(base_url=_BASE_URL)

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 3: named column access
        # Fix 1: removed contract_value — not stored in deployments table
        rows = conn.execute(
            "SELECT id, name, symbol, open_side, open_qty, open_price, venue "
            "FROM deployments WHERE status='running' AND open_side IS NOT NULL"
        ).fetchall()

    if not rows:
        return "Exposure Manager: No active positions."

    total_long_exposure  = 0.0
    total_short_exposure = 0.0
    position_lines       = []

    for row in rows:
        qty    = abs(float(row["open_qty"]   or 0))
        price  = float(row["open_price"] or 0)
        symbol = row["symbol"]
        venue  = row["venue"]

        # Fix 1+2: fetch contract value from API, not from DB column
        # Use live API for paper venues since they trade live instruments
        lookup_venue = "live" if venue in ("paper", "paper_live") else venue
        cv           = _get_contract_value(client, symbol)
        notional     = qty * price * cv

        if row["open_side"] == "buy":
            total_long_exposure  += notional
        elif row["open_side"] == "sell":
            total_short_exposure += notional

        position_lines.append(
            f"  {row['name']} ({symbol} {row['open_side']} "
            f"{qty} @ {price:.4f}) = ${notional:,.2f}"
        )

    net_exposure = total_long_exposure - total_short_exposure
    # Fix 6: use gross exposure (long + short) as the limit measure
    # max() underestimates risk when both sides are large
    gross_exposure = total_long_exposure + total_short_exposure

    now_str  = datetime.now(timezone.utc).isoformat() + "Z"
    messages = [
        "Exposure Summary:",
        f"  Long  Exposure : ${total_long_exposure:,.2f}",
        f"  Short Exposure : ${total_short_exposure:,.2f}",
        f"  Net   Delta    : ${net_exposure:,.2f}",
        f"  Gross Exposure : ${gross_exposure:,.2f}",
        f"  Limit          : ${limit:,.2f}",
        "",
        "Open Positions:",
    ] + position_lines

    if gross_exposure > limit:
        messages.append(
            f"\nCRITICAL: Gross exposure ${gross_exposure:,.2f} "
            f"exceeds limit ${limit:,.2f}."
        )

        # Pause all flat bots to prevent new positions opening
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            flat_bots = conn.execute(
                "SELECT id, name FROM deployments "
                "WHERE status='running' AND open_side IS NULL"
            ).fetchall()

            if flat_bots:
                for fb in flat_bots:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (fb["id"],),
                    )
                    # Fix 5: log audit event per bot
                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'exposure_manager', ?)",
                        (
                            fb["id"], now_str,
                            f"paused — gross exposure ${gross_exposure:,.2f} "
                            f"exceeds limit ${limit:,.2f}",
                        ),
                    )
                paused_names = [fb["name"] for fb in flat_bots]
                messages.append(
                    f"Paused {len(flat_bots)} flat bots to prevent further exposure: "
                    f"{', '.join(paused_names)}"
                )
            else:
                messages.append("No flat bots available to pause.")

    else:
        messages.append(f"Exposure is within safe limits (${gross_exposure:,.2f} / ${limit:,.2f}).")

        # Fix 4: auto-resume previously paused flat bots when exposure normalises
        if auto_resume:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                paused_bots = conn.execute(
                    "SELECT id, name FROM deployments "
                    "WHERE status='paused' AND open_side IS NULL "
                    "AND tag NOT IN ('circuit_breaker') "  # don't resume circuit-breaker pauses
                ).fetchall()

                resumed = []
                for pb in paused_bots:
                    conn.execute(
                        "UPDATE deployments SET status='running' WHERE id=?",
                        (pb["id"],),
                    )
                    # Fix 5: log audit event for resume
                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'exposure_manager', ?)",
                        (
                            pb["id"], now_str,
                            f"resumed — gross exposure ${gross_exposure:,.2f} "
                            f"back within limit ${limit:,.2f}",
                        ),
                    )
                    resumed.append(pb["name"])

                if resumed:
                    messages.append(
                        f"Resumed {len(resumed)} flat bots: {', '.join(resumed)}"
                    )

    return "### Exposure Manager\n\n" + "\n".join(messages)

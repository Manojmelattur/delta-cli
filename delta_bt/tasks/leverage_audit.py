"""Leverage Audit Task

Scans all running deployments and verifies that the leverage
set on Delta Exchange matches what is stored in the deployments table.

If a mismatch is found:
  - Logs a warning event on the deployment
  - If auto_fix=True, re-syncs leverage to Delta Exchange

This prevents silent leverage drift caused by:
  - Manual changes on the exchange UI
  - Failed leverage sync during entry
  - Exchange resets after liquidation

Params (set in task params_json):
    auto_fix       : If True, re-syncs mismatched leverage (default False)
    venue_filter   : Only audit this venue e.g. "live", "testnet" (default both)
    tolerance      : Allowed leverage difference before flagging (default 0.1)
"""
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


_BASE_LIVE    = "https://api.india.delta.exchange"
_BASE_TESTNET = "https://cdn-ind.testnet.deltaex.org"


def _client_for(venue: str) -> DeltaClient:
    """Return authenticated DeltaClient for the given venue."""
    import os
    if venue == "live":
        base = _BASE_LIVE
        key  = os.getenv("DELTA_LIVE_API_KEY",    "") or os.getenv("DELTA_API_KEY",    "")
        sec  = os.getenv("DELTA_LIVE_API_SECRET", "") or os.getenv("DELTA_API_SECRET", "")
    else:
        base = _BASE_TESTNET
        key  = os.getenv("DELTA_TESTNET_API_KEY",    "") or os.getenv("DELTA_API_KEY",    "")
        sec  = os.getenv("DELTA_TESTNET_API_SECRET", "") or os.getenv("DELTA_API_SECRET", "")
    return DeltaClient(base, key, sec)


def _get_exchange_leverage(client: DeltaClient, product_id: int) -> float:
    """Fetch current leverage for a product from Delta Exchange.

    Uses GET /v2/products/{product_id}/orders/leverage endpoint.
    Returns 0.0 if the call fails.
    """
    try:
        data = client._request(
            "GET",
            f"/v2/products/{product_id}/orders/leverage",
            auth=True,
        )
        return float(data.get("leverage") or 0)
    except Exception:
        return 0.0


def run(**kwargs):
    auto_fix      = bool(kwargs.get("auto_fix",      False))
    venue_filter  = kwargs.get("venue_filter",        None)
    tolerance     = float(kwargs.get("tolerance",     0.1))

    now_str = datetime.now(timezone.utc).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        query = """
            SELECT id, name, symbol, venue, leverage
            FROM deployments
            WHERE status = 'running'
              AND venue IN ('live', 'testnet')
              AND leverage IS NOT NULL
        """
        args = []
        if venue_filter:
            query += " AND venue = ?"
            args.append(venue_filter)

        rows = conn.execute(query, args).fetchall()

    if not rows:
        return (
            "Leverage Audit: No live or testnet deployments "
            "with configured leverage to audit."
        )

    messages  = []
    checked   = 0
    matched   = 0
    mismatched= 0
    fixed     = 0
    skipped   = 0
    errors    = []

    # Group by venue to reuse client per venue
    venue_groups: dict = {}
    for row in rows:
        v = row["venue"]
        if v not in venue_groups:
            venue_groups[v] = []
        venue_groups[v].append(dict(row))

    for venue, bots in venue_groups.items():
        try:
            client = _client_for(venue)
        except Exception as e:
            errors.append(f"ERR | Could not create client for venue {venue}: {e}")
            continue

        for bot in bots:
            dep_id       = bot["id"]
            name         = bot["name"]
            symbol       = bot["symbol"]
            stored_lev   = float(bot["leverage"] or 1)

            checked += 1

            # Get product ID
            try:
                prod       = client.get_product(symbol)
                product_id = int(prod["id"])
            except Exception as e:
                errors.append(
                    f"ERR | {name} ({symbol}): "
                    f"could not fetch product — {e}"
                )
                skipped += 1
                continue

            # Get current leverage from exchange
            exchange_lev = _get_exchange_leverage(client, product_id)

            if exchange_lev <= 0:
                errors.append(
                    f"WARN | {name} ({symbol}): "
                    f"could not fetch exchange leverage — skipping"
                )
                skipped += 1
                continue

            diff = abs(exchange_lev - stored_lev)

            if diff <= tolerance:
                matched += 1
                continue

            # Mismatch detected
            mismatched += 1
            messages.append(
                f"MISMATCH: {name} ({symbol} {venue}): "
                f"DB={stored_lev:.1f}x "
                f"Exchange={exchange_lev:.1f}x "
                f"diff={diff:.2f}x"
            )

            # Log warning event
            try:
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'leverage_audit', ?)",
                        (
                            dep_id, now_str,
                            f"Leverage mismatch detected — "
                            f"DB={stored_lev:.1f}x "
                            f"Exchange={exchange_lev:.1f}x",
                        ),
                    )
            except Exception as e:
                errors.append(
                    f"ERR | {name}: event log failed — {e}"
                )

            if auto_fix:
                # Re-sync leverage to Delta Exchange
                try:
                    client.set_leverage(product_id, stored_lev)

                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'leverage_audit', ?)",
                            (
                                dep_id, now_str,
                                f"Leverage re-synced — "
                                f"{exchange_lev:.1f}x -> {stored_lev:.1f}x",
                            ),
                        )
                    messages.append(
                        f"  Fixed: leverage re-synced "
                        f"{exchange_lev:.1f}x -> {stored_lev:.1f}x "
                        f"on {symbol} ({venue})"
                    )
                    fixed += 1
                except Exception as e:
                    err = (
                        f"ERR | {name} ({symbol}): "
                        f"leverage re-sync failed — {e}"
                    )
                    errors.append(err)
                    messages.append(f"  {err}")
            else:
                messages.append(
                    f"  auto_fix=False — no action taken. "
                    f"Set auto_fix=true in params_json to re-sync."
                )

    # Build summary
    summary = (
        f"Leverage Audit complete — "
        f"checked={checked}, "
        f"matched={matched}, "
        f"mismatched={mismatched}, "
        f"fixed={fixed}, "
        f"skipped={skipped}"
    )

    if not messages and not errors:
        return (
            f"### Leverage Audit\n\n"
            f"{summary}\n"
            f"All {checked} deployments have correct leverage on Delta Exchange."
        )

    messages.insert(0, summary)

    if not auto_fix and mismatched > 0:
        messages.append(
            "Note: Set auto_fix=true in params_json to automatically "
            "re-sync mismatched leverage to Delta Exchange."
        )

    if errors:
        messages.append("Errors:")
        messages.extend(errors)

    return "### Leverage Audit\n\n" + "\n".join(messages)

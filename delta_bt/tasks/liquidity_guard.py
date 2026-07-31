import os
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


# Fix 2: use env var for base URL consistent with rest of codebase
_BASE_URL = os.getenv("DELTA_LIVE_BASE_URL", "https://api.india.delta.exchange")


def _estimate_slippage(levels: list, size: float) -> float:
    """Walk order book levels to estimate average fill price slippage.

    Fix 5: spread alone does not capture slippage for large orders.
    This walks the book consuming `size` contracts and returns the
    volume-weighted average price deviation from best price as a %.

    Args:
        levels: list of {"price": str, "size": str} order book levels
        size:   number of contracts to fill

    Returns:
        slippage as a percentage of best price, or 0.0 if book is empty
    """
    if not levels or size <= 0:
        return 0.0

    best_price    = float(levels[0]["price"])
    remaining     = size
    total_cost    = 0.0
    total_filled  = 0.0

    for level in levels:
        level_price = float(level["price"])
        level_size  = float(level.get("size", level.get("quantity", 0)))

        fill        = min(remaining, level_size)
        total_cost  += fill * level_price
        total_filled+= fill
        remaining   -= fill

        if remaining <= 0:
            break

    if total_filled == 0 or best_price == 0:
        return 0.0

    vwap_fill  = total_cost / total_filled
    slippage   = abs(vwap_fill - best_price) / best_price * 100
    return slippage


def run(**kwargs):
    max_slippage_pct = float(kwargs.get("max_slippage_pct", 0.5))
    # Fix 4: auto-resume bots when spread returns to normal
    auto_resume      = bool(kwargs.get("auto_resume", True))

    # Fix 2: use DeltaClient for consistent base URL and error handling
    client = DeltaClient(base_url=_BASE_URL)

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 3: named column access
        rows = conn.execute(
            "SELECT id, name, symbol, size, open_side "
            "FROM deployments WHERE status IN ('running', 'paused')"
        ).fetchall()

    if not rows:
        return "Liquidity Guard: No deployments to monitor."

    messages = []
    paused   = 0
    resumed  = 0

    for row in rows:
        dep_id    = row["id"]
        name      = row["name"]
        symbol    = row["symbol"]
        size      = float(row["size"] or 1)
        open_side = row["open_side"]
        status    = row["status"] if "status" in row.keys() else "running"

        try:
            # Fix 1+2: use DeltaClient with correct base URL
            data = client._request("GET", f"/v2/l2orderbook/{symbol}")

            bids = data.get("buy",  [])
            asks = data.get("sell", [])

            if not bids or not asks:
                continue

            best_bid   = float(bids[0]["price"])
            best_ask   = float(asks[0]["price"])
            spread_pct = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0.0

            # Fix 5: estimate actual slippage by walking the book for `size` contracts
            # Use ask side for entries (buy), bid side for exits (sell)
            if not open_side:
                slippage_pct = _estimate_slippage(asks, size)
            else:
                exit_side    = bids if open_side == "buy" else asks
                slippage_pct = _estimate_slippage(exit_side, size)

            now_str      = datetime.now(timezone.utc).isoformat() + "Z"
            is_unhealthy = spread_pct > max_slippage_pct or slippage_pct > max_slippage_pct

            if is_unhealthy:
                messages.append(
                    f"WARN | {name} ({symbol}): "
                    f"spread={spread_pct:.3f}% slippage={slippage_pct:.3f}% "
                    f"(max={max_slippage_pct:.2f}%)"
                )

                # Fix 6: explicit None/empty check for open_side
                if (open_side is None or open_side == "") and status == "running":
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments SET status='paused' WHERE id=?",
                            (dep_id,),
                        )
                        # Fix 8: log audit event when pausing
                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'liquidity_guard', ?)",
                            (
                                dep_id, now_str,
                                f"paused — spread={spread_pct:.3f}% "
                                f"slippage={slippage_pct:.3f}% exceeds {max_slippage_pct:.2f}%",
                            ),
                        )
                    messages.append(f"> Paused {name} — spread/slippage too high for safe entry.")
                    paused += 1
                elif open_side:
                    messages.append(
                        f"> Position open on {name} — cannot pause. "
                        f"Monitor exit carefully."
                    )

            else:
                # Fix 4: auto-resume previously paused flat bots when spread normalises
                if auto_resume and status == "paused" and (open_side is None or open_side == ""):
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments SET status='running' WHERE id=?",
                            (dep_id,),
                        )
                        # Fix 8: log audit event when resuming
                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'liquidity_guard', ?)",
                            (
                                dep_id, now_str,
                                f"resumed — spread={spread_pct:.3f}% "
                                f"slippage={slippage_pct:.3f}% back within {max_slippage_pct:.2f}%",
                            ),
                        )
                    messages.append(
                        f"> Resumed {name} ({symbol}) — "
                        f"spread={spread_pct:.3f}% slippage={slippage_pct:.3f}% normalised."
                    )
                    resumed += 1

        # Fix 7: log errors instead of silently continuing
        except Exception as e:
            messages.append(f"ERR | {name} ({symbol}): {e}")

    if not messages:
        return "Liquidity Guard: Order book depth and spreads are healthy."

    summary = (
        f"Liquidity Guard complete — "
        f"paused={paused}, resumed={resumed}, warnings={len(messages)}"
    )
    messages.insert(0, summary)
    return "### Liquidity Guard Report\n\n" + "\n\n".join(messages)

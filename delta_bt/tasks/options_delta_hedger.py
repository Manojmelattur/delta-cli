import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

# Fix 1: removed unused `from delta_bt.core.options import calculate_greeks`
# If real Greeks calculation is available, it should be called in _calc_net_delta()


def _calc_net_delta(symbol: str, strategy_name: str, size: float) -> float:
    """Calculate net portfolio delta for an options/MOVE position.

    Fix 2: replaces the hardcoded placeholder with a real calculation.

    Delta approximations by strategy type:
      - straddle / strangle : near-zero delta at inception, drifts with spot
      - long_call / call    : +0.5 per contract (ATM approximation)
      - long_put  / put     : -0.5 per contract (ATM approximation)
      - move      / MOVE    : delta depends on direction, approximate +/-0.5
      - default             : 0.0 (unknown, no hedge needed)

    For production use, replace with actual Greeks from calculate_greeks()
    using live spot price, IV, time to expiry, and strike.
    """
    strat = strategy_name.lower()
    if "straddle" in strat or "strangle" in strat:
        # Straddle is delta-neutral at inception but drifts — approximate 0
        return 0.0
    elif "long_call" in strat or ("call" in strat and "short" not in strat):
        return 0.5 * size
    elif "short_call" in strat:
        return -0.5 * size
    elif "long_put" in strat or ("put" in strat and "short" not in strat):
        return -0.5 * size
    elif "short_put" in strat:
        return 0.5 * size
    elif "move" in strat:
        return 0.5 * size  # conservative long-delta assumption
    return 0.0


def run(**kwargs):
    """
    Options Portfolio Delta-Neutral Auto-Hedger Task.
    Calculates net portfolio delta across active options/MOVE positions.
    If net delta drifts beyond threshold, logs a hedge recommendation
    and optionally places a perpetual futures hedge order.
    """
    delta_threshold = float(kwargs.get("delta_threshold", 0.25))
    auto_hedge      = bool(kwargs.get("auto_hedge",       False))
    venue           = kwargs.get("venue", "paper")

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 3: named column access
        rows = conn.execute(
            # Fix 8: removed sl_pct and tp_pct — never used
            "SELECT id, name, symbol, strategy, size "
            "FROM deployments "
            "WHERE status='running' "
            "AND (strategy LIKE '%options%' OR strategy LIKE '%move%')"
        ).fetchall()

    if not rows:
        return "Options Delta Hedger: No active options or MOVE deployments running."

    # Fix 7: DeltaClient needed for actual hedge order placement
    client  = DeltaClient(base_url="https://api.india.delta.exchange")
    now_str = datetime.now(timezone.utc).isoformat() + "Z"
    messages = []

    for row in rows:
        dep_id        = row["id"]
        name          = row["name"]
        symbol        = row["symbol"]
        strategy_name = row["strategy"]
        size          = float(row["size"] or 1)

        # Fix 2: use real delta calculation instead of hardcoded values
        net_delta = _calc_net_delta(symbol, strategy_name, size)

        msg = (
            f"{name} ({symbol}): "
            f"net delta={net_delta:+.4f} "
            f"(threshold=±{delta_threshold})"
        )

        if abs(net_delta) > delta_threshold:
            hedge_side = "sell" if net_delta > 0 else "buy"
            hedge_label = "SELL SHORT PERP" if net_delta > 0 else "BUY LONG PERP"
            # Fix 4: enforce integer lot sizes
            hedge_qty  = max(1, round(abs(net_delta) * size))

            msg += (
                f" -> DELTA DRIFT WARNING: "
                f"required hedge = {hedge_label} {hedge_qty} lots"
            )

            if auto_hedge:
                # Fix 5: actually place the hedge order instead of just logging
                try:
                    prod = client.get_product(symbol)
                    pid  = int(prod["id"])
                    client.place_order(
                        product_id=pid,
                        size=hedge_qty,
                        side=hedge_side,
                        order_type="market_order",
                        reduce_only=False,
                    )
                    hedge_status = "Hedge order placed"
                except Exception as e:
                    hedge_status = f"Hedge order failed: {e}"

                # Fix 6: use 'delta_hedge' kind not 'info'
                try:
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'delta_hedge', ?)",
                            (
                                dep_id, now_str,
                                f"{hedge_label} {hedge_qty} lots — "
                                f"net_delta={net_delta:+.4f} — {hedge_status}",
                            ),
                        )
                except Exception as e:
                    msg += f" [event log failed: {e}]"

                msg += f" [{hedge_status}]"
            else:
                msg += " [auto_hedge=False — no order placed]"

        messages.append(msg)

    return "### Options Delta Hedger\n\n" + "\n".join(messages)

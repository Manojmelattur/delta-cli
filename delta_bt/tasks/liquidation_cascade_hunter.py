from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


# Fix 3: removed unused `import math`
DEFAULT_PAIRS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD",
    "AVAXUSD", "DOGEUSD", "LINKUSD", "SUIUSD",
]


def run(**kwargs):
    """
    Liquidation Cascade Hunter Task.
    Scans top perpetual pairs for violent liquidation wicks on 5-minute candles
    and flags mean-reversion scalp bounce opportunities.
    """
    min_wick_pct = float(kwargs.get("min_wick_pct", 3.0))
    auto_deploy  = bool(kwargs.get("auto_deploy",   False))
    lot_size     = float(kwargs.get("lot_size",     1.0))
    venue        = kwargs.get("venue", "paper")
    # Fix 8: how many recent bars to scan (default 3 = last 15 minutes of 5m bars)
    scan_bars    = int(kwargs.get("scan_bars", 3))

    # Fix 1: correct base URL
    client     = DeltaClient(base_url="https://api.india.delta.exchange")
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=3)

    messages      = []
    opportunities = []

    for symbol in DEFAULT_PAIRS:
        try:
            bars = client.candles(symbol, "5m", start_time, end_time)
            if not bars or len(bars) < 3:
                continue

            # Fix 8: scan last `scan_bars` bars instead of only the last one
            recent_bars = bars[-scan_bars:]

            for bar in recent_bars:
                # Fix 2: client.candles() returns dicts — use key access not attributes
                high     = float(bar["high"])
                low      = float(bar["low"])
                open_px  = float(bar["open"])
                close_px = float(bar["close"])

                if low <= 0 or open_px <= 0 or close_px <= 0:
                    continue

                body_bottom = min(open_px, close_px)
                body_top    = max(open_px, close_px)

                lower_wick_pct = ((body_bottom - low)  / low)      * 100.0
                upper_wick_pct = ((high - body_top)    / body_top) * 100.0

                if lower_wick_pct >= min_wick_pct:
                    opportunities.append({
                        "symbol":    symbol,
                        "direction": "long",
                        "wick_pct":  lower_wick_pct,
                        "price":     close_px,
                    })
                    messages.append(
                        f"Liquidation Long Sweep on {symbol}: "
                        f"{lower_wick_pct:.2f}% lower wick @ {close_px:.4f}"
                    )
                    # Only report the first qualifying bar per symbol per direction
                    break

                elif upper_wick_pct >= min_wick_pct:
                    opportunities.append({
                        "symbol":    symbol,
                        "direction": "short",
                        "wick_pct":  upper_wick_pct,
                        "price":     close_px,
                    })
                    messages.append(
                        f"Liquidation Short Sweep on {symbol}: "
                        f"{upper_wick_pct:.2f}% upper wick @ {close_px:.4f}"
                    )
                    break

        # Fix 7: log errors instead of silently continuing
        except Exception as e:
            messages.append(f"ERR | {symbol}: {e}")

    if auto_deploy and opportunities:
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        i_live  = 1 if venue == "live" else 0

        for opp in opportunities:
            try:
                with connect() as conn:
                    # Fix 5: check by symbol + strategy + tag instead of name
                    existing = conn.execute(
                        "SELECT id FROM deployments "
                        "WHERE symbol=? AND strategy=? AND tag=? AND status='running'",
                        (opp["symbol"], "vwap_bands", "liquidation_cascade_hunter"),
                    ).fetchone()

                    if existing:
                        messages.append(
                            f"> Skipped: vwap_bands already running on {opp['symbol']}."
                        )
                        continue

                    # Fix 4: complete INSERT with all required columns
                    bot_name = f"Cascade Bounce {opp['symbol']} {opp['direction'].upper()}"
                    info = conn.execute(
                        """INSERT INTO deployments(
                            name, venue, strategy, symbol, resolution, size, params_json,
                            sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                            reduce_only, interval_sec, status, i_understand_live, leverage,
                            sync_leverage, force_entry, created_at, started_at, tag
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                        (
                            bot_name, venue, "vwap_bands",
                            opp["symbol"], "5m", lot_size, "{}",
                            1.5, 3.0, 1.0, 1.5, 0.0,
                            0, 60, i_live, 1, 1, 0,
                            now_str, now_str, "liquidation_cascade_hunter",
                        ),
                    )
                    dep_id = info.lastrowid
                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'start', ?)",
                        (dep_id, now_str, f"auto-deployed by Liquidation Cascade Hunter "
                                          f"({opp['direction']} wick {opp['wick_pct']:.2f}%)"),
                    )
                    messages.append(
                        f"> Auto-Deployed Bot #{dep_id}: {bot_name} "
                        f"(SL 1.5% TP 3.0% Trail 1.0% activates at +1.5%)"
                    )
            except Exception as e:
                messages.append(f"ERR | deploy failed for {opp['symbol']}: {e}")

    if not messages:
        return (
            "Liquidation Cascade Hunter: No violent liquidation wicks detected "
            "in current 5m window."
        )

    return "### Liquidation Cascade Hunter\n\n" + "\n".join(messages)

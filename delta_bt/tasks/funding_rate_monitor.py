import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


# Strategies considered trend-following — configurable via kwargs
_DEFAULT_TREND_STRATEGIES = {
    "ema3", "ema_cross", "macd", "momentum_breakout",
    "keltner_squeeze", "supertrend",
}


def run(**kwargs):
    extreme_threshold_pct = float(kwargs.get("extreme_threshold_pct", 100.0))
    auto_resume           = bool(kwargs.get("auto_resume", True))
    # Fix 6: configurable trend strategy set instead of substring matching
    trend_strategies      = set(kwargs.get("trend_strategies", _DEFAULT_TREND_STRATEGIES))

    # Fix 1: correct base URL
    client  = DeltaClient(base_url="https://api.india.delta.exchange")
    tickers = client.tickers(contract_types="perpetual_futures")

    now_str  = datetime.now(timezone.utc).isoformat() + "Z"
    messages = []
    paused   = 0
    resumed  = 0

    # Collect extreme funding symbols for auto-resume check
    extreme_symbols = set()

    for t in tickers:
        sym = t.get("symbol")
        fr  = t.get("funding_rate")

        if not sym or fr is None:
            continue

        # Fix 2: Delta Exchange funding is paid every 8 hours (3x per day)
        # APY = rate_per_interval * intervals_per_day * 365 * 100
        # Default interval = 8h → 3 intervals/day
        # For accuracy, product_specs.rate_exchange_interval should be used per symbol
        intervals_per_day = float(kwargs.get("intervals_per_day", 3))
        apy = float(fr) * intervals_per_day * 365 * 100

        if abs(apy) > extreme_threshold_pct:
            extreme_symbols.add(sym)
            direction = "POSITIVE" if apy > 0 else "NEGATIVE"
            crowd     = "LONG"     if apy > 0 else "SHORT"

            messages.append(
                f"Extreme {direction} funding on {sym}: "
                f"APY={apy:.2f}% — crowd is heavily {crowd}."
            )

            # Pause flat trend-following bots on this symbol
            # Fix 7: clarified — only flat bots are paused (prevents new entries)
            # open positions are flagged separately below
            with connect() as conn:
                conn.row_factory = sqlite3.Row  # Fix 3: named column access
                rows = conn.execute(
                    "SELECT id, name, strategy FROM deployments "
                    "WHERE status='running' AND symbol=? AND open_side IS NULL",
                    (sym,),
                ).fetchall()

                for row in rows:
                    # Fix 6: exact strategy name match instead of substring
                    if row["strategy"].lower() in trend_strategies:
                        conn.execute(
                            "UPDATE deployments SET status='paused' WHERE id=?",
                            (row["id"],),
                        )
                        # Fix 5: log audit event
                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'funding_monitor', ?)",
                            (
                                row["id"], now_str,
                                f"paused — extreme {direction} funding APY={apy:.2f}% "
                                f"on {sym}, crowd={crowd}",
                            ),
                        )
                        messages.append(
                            f"> Paused trend bot {row['name']} "
                            f"— prevents new {crowd} entry into crowded sentiment."
                        )
                        paused += 1

                # Fix 7: flag open positions separately with a warning (cannot pause)
                open_rows = conn.execute(
                    "SELECT id, name, strategy, open_side FROM deployments "
                    "WHERE status='running' AND symbol=? AND open_side IS NOT NULL",
                    (sym,),
                ).fetchall()

                for row in open_rows:
                    if row["strategy"].lower() in trend_strategies:
                        open_side = row["open_side"]
                        if (crowd == "LONG" and open_side == "buy") or \
                           (crowd == "SHORT" and open_side == "sell"):
                            messages.append(
                                f"> WARN: {row['name']} has open {open_side} position "
                                f"aligned with crowded {crowd} sentiment — monitor closely."
                            )

    # Fix 4: auto-resume previously paused bots on symbols where funding normalised
    if auto_resume:
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            paused_bots = conn.execute(
                "SELECT id, name, symbol FROM deployments "
                "WHERE status='paused' AND open_side IS NULL"
            ).fetchall()

            for pb in paused_bots:
                # Only resume if this symbol is no longer in extreme funding
                if pb["symbol"] not in extreme_symbols:
                    conn.execute(
                        "UPDATE deployments SET status='running' WHERE id=?",
                        (pb["id"],),
                    )
                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'funding_monitor', ?)",
                        (
                            pb["id"], now_str,
                            f"resumed — funding rate on {pb['symbol']} "
                            f"back within normal bounds",
                        ),
                    )
                    messages.append(
                        f"> Resumed {pb['name']} ({pb['symbol']}) — "
                        f"funding rate normalised."
                    )
                    resumed += 1

    if not messages:
        return "Funding Rate Monitor: All funding rates within normal bounds."

    # Fix 8: removed unused `actions` counter — use paused/resumed instead
    summary = (
        f"Funding Monitor complete — "
        f"paused={paused}, resumed={resumed}, "
        f"extreme_symbols={len(extreme_symbols)}"
    )
    messages.insert(0, summary)
    return "### Funding Sentiment Monitor\n\n" + "\n\n".join(messages)

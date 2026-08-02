import json
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def run(**kwargs):
    # Fix 1: correct base URL
    client = DeltaClient(base_url="https://api.india.delta.exchange")
    venue       = str(kwargs.get("venue",         "paper"))
    user_symbols_raw = kwargs.get("coins", kwargs.get("symbols", kwargs.get("symbol_list", [])))
    user_symbols = []
    if isinstance(user_symbols_raw, str):
        user_symbols = [s.strip() for s in user_symbols_raw.split(",") if s.strip()]
    elif isinstance(user_symbols_raw, list):
        user_symbols = [str(s).strip() for s in user_symbols_raw if str(s).strip()]

    if user_symbols:
        symbols = user_symbols
    else:
        tickers = client.tickers(contract_types="perpetual_futures")
        symbols = [t["symbol"] for t in tickers if "symbol" in t]

    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=7)

    messages = []

    for sym in symbols:
        try:
            klines = client.candles(sym, "1h", start_time, end_time)
            if len(klines) < 24:
                continue

            # Use last 24 bars (24h) for VWAP and std dev
            last_24 = klines[-24:]

            total_vol       = 0.0
            total_price_vol = 0.0

            for k in last_24:
                vol  = float(k["volume"])
                hlc3 = (float(k["high"]) + float(k["low"]) + float(k["close"])) / 3
                total_vol       += vol
                total_price_vol += hlc3 * vol

            if total_vol == 0:
                continue

            vwap = total_price_vol / total_vol

            variance = sum(
                (float(k["close"]) - vwap) ** 2 for k in last_24
            ) / len(last_24)
            std_dev = variance ** 0.5

            last_close = float(last_24[-1]["close"])
            z_score    = (last_close - vwap) / std_dev if std_dev > 0 else 0.0

            # Fix 6: lowered threshold from 3.0 to 2.0 for practical signal frequency
            if abs(z_score) > 2.0:
                direction = "OVERBOUGHT" if z_score > 0 else "OVERSOLD"
                messages.append(
                    f"{sym} is heavily {direction} "
                    f"(Z-Score: {z_score:.2f}) -> Mean reversion likely."
                )

                with connect() as conn:
                    existing = conn.execute(
                        "SELECT id FROM deployments "
                        "WHERE symbol=? AND strategy='vwap' AND status='running'",
                        (sym,),
                    ).fetchone()

                    if existing:
                        messages.append(f"> VWAP bot already running on {sym}.")
                        continue

                    now  = datetime.now(timezone.utc).isoformat()
                    # Fix 7: removed redundant "vwap_reversion_hunter_" prefix
                    name = f"VWAP Reversion {sym}"
                    size = float(kwargs.get("base_lot_size", 1.0))

                    info = conn.execute(
                        """INSERT INTO deployments(
                            name, venue, strategy, symbol, resolution, size, params_json,
                            sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                            reduce_only, interval_sec, status, i_understand_live, leverage,
                            sync_leverage, force_entry, created_at, started_at, tag
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                        (
                            name, venue, "vwap", sym, "15m", size, "{}",
                            2.0, 4.0, 0.0, 0.0, 0.0,
                            0, 300, 0, 1, 1, 0,
                            now, now, "vwap_hunter",
                        ),
                    )
                    dep_id = info.lastrowid

                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'start', ?)",
                        (dep_id, now, "auto-deployed by VWAP Hunter"),
                    )

                    messages.append(
                        f"> Auto-Deployed Bot #{dep_id}. "
                        f"Venue: {venue}, TP: 4%, SL: 2%."
                    )

        # Fix 4: log errors instead of silently swallowing them
        except Exception as e:
            messages.append(f"ERR | {sym}: {e}")

    if not messages:
        return "VWAP Reversion Hunter: No extreme overextensions detected."

    return "### VWAP Reversion Hunter\n\n" + "\n\n".join(messages)

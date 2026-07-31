import json
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def run(**kwargs):
    # Fix 1: correct base URL
    client = DeltaClient(base_url="https://api.india.delta.exchange")

    # Get top 10 symbols by USD turnover
    tickers = client.tickers(contract_types="perpetual_futures")
    tickers.sort(
        key=lambda x: float(x.get("turnover_usd") or x.get("turnover") or 0),
        reverse=True,
    )
    symbols = [t["symbol"] for t in tickers[:10] if "symbol" in t]

    end_time   = datetime.now(timezone.utc)
    # Fix 2: fetch 60 bars so klines[-20:-1] always has enough data
    start_time = end_time - timedelta(minutes=60)
    venue       = str(kwargs.get("venue",         "paper"))
    messages = []

    for sym in symbols:
        try:
            klines = client.candles(sym, "1m", start_time, end_time)
            if len(klines) < 20:
                continue

            # Average volume of the 19 bars before the last bar
            volumes = [float(k["volume"]) for k in klines[-20:-1]]
            avg_vol = sum(volumes) / len(volumes)

            last_candle = klines[-1]
            last_vol    = float(last_candle["volume"])

            if avg_vol == 0:
                continue

            # Fix 5: use a multiplier instead of percentage for clarity
            vol_multiple = last_vol / avg_vol

            if vol_multiple > 5.0:  # 5x average volume
                messages.append(
                    f"VOLUME ANOMALY on {sym}: "
                    f"1m volume spiked to {vol_multiple:.1f}x average."
                )

                with connect() as conn:
                    existing = conn.execute(
                        "SELECT id FROM deployments "
                        "WHERE symbol=? AND strategy='momentum_breakout' AND status='running'",
                        (sym,),
                    ).fetchone()

                    if existing:
                        messages.append(
                            f"> Breakout bot already running on {sym}."
                        )
                        continue

                    now  = datetime.now(timezone.utc).isoformat()
                    # Fix 4: removed redundant "volume_anomaly_sniper_" prefix
                    name = f"Breakout Sniper {sym}"
                    size = float(kwargs.get("base_lot_size", 1.0))

                    info = conn.execute(
                        """INSERT INTO deployments(
                            name, venue, strategy, symbol, resolution, size, params_json,
                            sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                            reduce_only, interval_sec, status, i_understand_live, leverage,
                            sync_leverage, force_entry, created_at, started_at, tag
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                        (
                            name,venue, "momentum_breakout", sym, "1m", size, "{}",
                            2.0, 0.0, 1.0,
                            # Fix 3: trail_activate_pct=1.0 so trail only kicks in
                            # after 1% profit — prevents immediate trail-stop on entry
                            1.0, 0.0,
                            0, 300, 1, 1, 1, 0,
                            now, now, "volume_sniper",
                        ),
                    )
                    dep_id = info.lastrowid

                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'start', ?)",
                        (dep_id, now, "auto-deployed by Volume Sniper"),
                    )

                    messages.append(
                        f"> Auto-Deployed Breakout Bot #{dep_id} on {sym}. "
                        f"Venue: {venue}, SL: 2%, TSL: 1% (activates at +1%)."
                    )

        # Fix 6: log errors instead of silently swallowing them
        except Exception as e:
            messages.append(f"ERR | {sym}: {e}")

    if not messages:
        return "Volume Anomaly Sniper: No abnormal volume detected in the last minute."

    return "### Volume Anomaly Sniper\n\n" + "\n\n".join(messages)

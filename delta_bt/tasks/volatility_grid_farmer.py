import json
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def run(**kwargs):
    # Fix 1: correct base URL
    # Fix 2: removed unused `import math`
    client = DeltaClient(base_url="https://api.india.delta.exchange")
    venue =str(kwargs.get("venue","paper"))
    user_symbols_raw = kwargs.get("symbols") or kwargs.get("symbol_list")
    user_symbols = []
    if isinstance(user_symbols_raw, str):
        user_symbols = [s.strip() for s in user_symbols_raw.split(",") if s.strip()]
    elif isinstance(user_symbols_raw, list):
        user_symbols = [str(s).strip() for s in user_symbols_raw if str(s).strip()]

    if user_symbols:
        symbols = user_symbols
    else:
        tickers = client.tickers(contract_types="perpetual_futures")
        tickers.sort(
            key=lambda x: float(x.get("turnover_usd") or x.get("turnover") or 0),
            reverse=True,
        )
        symbols = [t["symbol"] for t in tickers[:15] if "symbol" in t]

    end_time   = datetime.now(timezone.utc)
    # Fix 3: fetch exactly 20 bars needed for the calculation
    start_time = end_time - timedelta(hours=20)

    messages = []

    for sym in symbols:
        try:
            klines = client.candles(sym, "1h", start_time, end_time)
            if len(klines) < 20:
                continue

            closes     = [float(k["close"]) for k in klines[-20:]]
            mean_close = sum(closes) / len(closes)
            std_dev    = (
                sum((c - mean_close) ** 2 for c in closes) / len(closes)
            ) ** 0.5

            vol_pct = (std_dev / mean_close) * 100

            # Fix 6: raised threshold from 0.5% to 1.5% — more practical
            # for 1h candles where even ranging markets show 0.5-1% std dev
            if vol_pct < 1.5:
                messages.append(
                    f"{sym} has low volatility ({vol_pct:.2f}% std dev). "
                    f"Suitable for Grid Farming."
                )

                with connect() as conn:
                    existing = conn.execute(
                        "SELECT id FROM deployments "
                        "WHERE symbol=? AND strategy='grid' AND status='running'",
                        (sym,),
                    ).fetchone()

                    if existing:
                        messages.append(
                            f"> Grid bot already running on {sym}."
                        )
                        continue

                    now  = datetime.now(timezone.utc).isoformat()
                    # Fix 5: removed redundant "volatility_grid_farmer_" prefix
                    name = f"Grid Farmer {sym}"
                    size = float(kwargs.get("base_lot_size", 1.0))

                    info = conn.execute(
                        """INSERT INTO deployments(
                            name, venue, strategy, symbol, resolution, size, params_json,
                            sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                            reduce_only, interval_sec, status, i_understand_live, leverage,
                            sync_leverage, force_entry, created_at, started_at, tag
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                        (
                            name, venue, "grid", sym, "15m", size, "{}",
                            # Fix 4: sl_pct=2.0, tp_pct=2.0 — equal risk/reward
                            2.0, 2.0, 0.0, 0.0, 0.0,
                            0, 300, 1, 1, 1, 0,
                            now, now, "grid_farmer",
                        ),
                    )
                    dep_id = info.lastrowid

                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'start', ?)",
                        (dep_id, now, "auto-deployed by Grid Farmer"),
                    )

                    messages.append(
                        f"> Auto-Deployed Grid Bot #{dep_id} on {sym}. "
                        f"Venue: {venue}, SL: 2%, TP: 2%."
                    )

        # Fix 7: log errors instead of silently swallowing them
        except Exception as e:
            messages.append(f"ERR | {sym}: {e}")

    if not messages:
        return "Grid Farmer: Markets are trending. No grid conditions detected."

    return "### Volatility Contraction & Grid Farmer\n\n" + "\n\n".join(messages)

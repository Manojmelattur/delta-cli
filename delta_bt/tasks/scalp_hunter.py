import json
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def calc_rsi(closes, n=14):
    if len(closes) < n + 1:
        return []

    gains  = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n

    rsi = []
    if avg_loss == 0:
        rsi.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100.0 - (100.0 / (1.0 + rs)))

    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n

        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100.0 - (100.0 / (1.0 + rs)))

    return rsi


def run(**kwargs):
    client      = DeltaClient(base_url="https://api.india.delta.exchange")
    auto_deploy = kwargs.get("auto_deploy", False)

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

    end   = datetime.now(timezone.utc)
    # Fix 2: fetch 200 bars for reliable RSI-14 Wilder smoothing
    start = end - timedelta(minutes=200)

    messages = []
    signals  = 0   # Fix 7: renamed from actions — counts signals found
    deployed = 0   # Fix 7: separate counter for actual deployments

    for sym in symbols:
        try:
            candles = client.candles(sym, "1m", start, end)
            if len(candles) < 30:
                continue

            closes = [float(c["close"]) for c in candles]
            opens  = [float(c["open"])  for c in candles]

            rsi_vals = calc_rsi(closes, 14)
            if not rsi_vals:
                continue

            current_rsi = rsi_vals[-1]
            last_close  = closes[-1]
            last_open   = opens[-1]

            # Scalp logic: RSI extreme + confirming candle colour
            signal = None
            if current_rsi < 25 and last_close > last_open:
                signal = "LONG"
            elif current_rsi > 75 and last_close < last_open:
                signal = "SHORT"

            if signal:
                signals += 1
                messages.append(
                    f"Scalp Setup: {sym} {signal} trigger! "
                    f"1m RSI: {current_rsi:.1f} @ {last_close}"
                )

                if auto_deploy:
                    with connect() as conn:
                        existing = conn.execute(
                            "SELECT id FROM deployments "
                            "WHERE symbol=? AND tag='scalp_hunter' AND status='running'",
                            (sym,),
                        ).fetchone()

                        if existing:
                            messages.append(
                                f"> Skipped auto-deploy: Scalp already running on {sym}."
                            )
                            continue

                        now  = datetime.now(timezone.utc).isoformat()
                        # Fix 4: removed redundant "scalp_hunter_" prefix
                        name = f"1m Scalp {sym}"
                        size = float(kwargs.get("base_lot_size", 1.0))

                        params_str = json.dumps({
                            "force_entry_side": "buy" if signal == "LONG" else "sell"
                        })

                        info = conn.execute(
                            """INSERT INTO deployments(
                                name, venue, strategy, symbol, resolution, size, params_json,
                                sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                                reduce_only, interval_sec, status, i_understand_live, leverage,
                                sync_leverage, force_entry, created_at, started_at, tag
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                            (
                                name, "paper",
                                # Fix 5: use rsi_mr strategy not vwap_reversion
                                "rsi_mr",
                                sym, "1m", size, params_str,
                                1.0, 1.5, 0.25, 0.5, 0.5,
                                # Fix 6: correct column order
                                # reduce_only, interval_sec, i_understand_live,
                                # leverage, sync_leverage, force_entry
                                0, 60, 1, 1, 1, 1,
                                now, now, "scalp_hunter",
                            ),
                        )
                        dep_id = info.lastrowid

                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'start', ?)",
                            (dep_id, now, "auto-deployed by Scalp Hunter"),
                        )
                        deployed += 1
                        messages.append(
                            f"> Deployed Scalp Bot #{dep_id} on {sym}."
                        )
                else:
                    messages.append("> Auto-deploy is OFF.")

        except Exception as e:
            messages.append(f"ERR | {sym}: {e}")

    # Fix 7: use signals counter for "nothing found" check
    if signals == 0:
        return f"Scanned {len(symbols)} symbols. No 1m Scalp setups found."

    return "### High-Frequency Scalp Hunter\n\n" + "\n\n".join(messages)

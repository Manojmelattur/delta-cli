import json
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def ema(prices, period):
    if not prices or len(prices) < period:
        return prices[-1] if prices else 0.0
    k       = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period
    for p in prices[period:]:
        ema_val = (p - ema_val) * k + ema_val
    return ema_val


def run(**kwargs):
    # Fix 1: correct base URL
    client = DeltaClient(base_url="https://api.india.delta.exchange")

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 4: named column access
        rows = conn.execute(
            # Fix 5: include params_json in the initial SELECT
            # to avoid a second query per deployment inside the loop
            "SELECT id, name, symbol, params_json "
            "FROM deployments WHERE status='running'"
        ).fetchall()

    if not rows:
        return "MTF Trend Enforcer: No active deployments to manage."

    # Get unique symbols
    symbols = list(set(r["symbol"] for r in rows))

    end_time   = datetime.now(timezone.utc)
    # 70 days gives a comfortable buffer for EMA-50 on daily candles
    start_time = end_time - timedelta(days=70)

    messages     = []
    actions      = 0
    macro_trends = {}

    for sym in symbols:
        try:
            klines = client.candles(sym, "1d", start_time, end_time)

            # Fix 2: require at least 50 bars so EMA-50 is meaningful
            # fewer bars would fall back to last_close and force NEUTRAL
            if len(klines) < 50:
                # Fix 6: log skipped symbols instead of silently passing
                macro_trends[sym] = "NEUTRAL"
                messages.append(
                    f"WARN | {sym}: only {len(klines)} daily bars available "
                    f"(need 50 for EMA-50) — defaulting to NEUTRAL"
                )
                continue

            closes     = [float(k["close"]) for k in klines]
            ema_20     = ema(closes, 20)
            ema_50     = ema(closes, 50)
            last_close = closes[-1]

            if last_close > ema_20 and ema_20 > ema_50:
                macro_trends[sym] = "BULLISH"
            elif last_close < ema_20 and ema_20 < ema_50:
                macro_trends[sym] = "BEARISH"
            else:
                macro_trends[sym] = "NEUTRAL"

        # Fix 6: log errors instead of silently swallowing them
        except Exception as e:
            macro_trends[sym] = "NEUTRAL"
            messages.append(f"ERR | {sym}: failed to fetch daily bars — {e}")

    for row in rows:
        dep_id = row["id"]
        name   = row["name"]
        sym    = row["symbol"]
        trend  = macro_trends.get(sym, "NEUTRAL")

        try:
            # Fix 5: use params_json from the initial SELECT
            params          = json.loads(row["params_json"] or "{}")
            current_allowed = params.get("allowed_side", "both")

            if trend == "BULLISH":
                new_allowed = "long"
            elif trend == "BEARISH":
                new_allowed = "short"
            else:
                new_allowed = "both"

            if current_allowed != new_allowed:
                params["allowed_side"] = new_allowed
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET params_json=? WHERE id=?",
                        (json.dumps(params), dep_id),
                    )
                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'mtf_enforcer', ?)",
                        (
                            dep_id,
                            datetime.now(timezone.utc).isoformat() + "Z",
                            f"allowed_side changed {current_allowed} -> {new_allowed} "
                            f"(macro trend: {trend})",
                        ),
                    )
                # Fix 7: note that strategy must read allowed_side from params_json
                messages.append(
                    f"{name} ({sym}): macro trend is {trend} — "
                    f"allowed_side changed {current_allowed} -> {new_allowed}. "
                    f"Note: strategy must read allowed_side from params_json."
                )
                actions += 1

        except Exception as e:
            messages.append(f"ERR | {name} ({sym}): failed to update — {e}")

    if actions == 0:
        return "MTF Trend Enforcer: All bot directions are aligned with the macro trend."

    return "### MTF Macro Trend Enforcer\n\n" + "\n\n".join(messages)

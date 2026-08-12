import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


# Cache contract values to avoid repeated API calls per deployment
_CV_CACHE: dict = {}


def _get_contract_value(client: DeltaClient, symbol: str) -> float:
    """Fetch contract value from Delta API with in-memory cache."""
    if symbol in _CV_CACHE:
        return _CV_CACHE[symbol]
    try:
        prod = client.get_product(symbol)
        cv   = float(prod.get("contract_value") or 1) or 1.0
    except Exception:
        cv = 1.0
    _CV_CACHE[symbol] = cv
    return cv


def _calculate_atr(bars: list, period: int = 14) -> float:
    """Calculate simple ATR over last `period` bars using Wilder's method."""
    if len(bars) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(bars)):
        # Fix 2: client.candles() returns dicts — use key access not attributes
        high       = float(bars[i]["high"])
        low        = float(bars[i]["low"])
        prev_close = float(bars[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    return sum(tr_list[-period:]) / float(period)


def _regime_multiplier(bars: list, period: int = 14, baseline_window: int = 60) -> tuple:
    """
    Volatility-regime risk multiplier.
    Compares current ATR%% against the median ATR%% over a longer baseline
    window. Returns (multiplier, regime_label, ratio).

      ratio = current_atr / baseline_atr
        ratio >= 2.0   -> extreme vol  -> 0.40x risk
        ratio >= 1.5   -> high vol     -> 0.60x risk
        ratio >= 1.15  -> elevated     -> 0.80x risk
        0.85..1.15     -> normal       -> 1.00x risk
        ratio <  0.85  -> calm         -> 1.20x risk (small boost)
    """
    if len(bars) < baseline_window + period:
        return 1.0, "normal(insufficient-history)", 1.0

    # Rolling ATR series over the baseline window
    atrs = []
    for end in range(period + 1, len(bars) + 1):
        window = bars[end - period - 1:end]
        atrs.append(_calculate_atr(window, period))
    atrs = [a for a in atrs if a > 0]
    if len(atrs) < 10:
        return 1.0, "normal(insufficient-atr)", 1.0

    current = atrs[-1]
    hist    = sorted(atrs[-baseline_window:])
    median  = hist[len(hist) // 2]
    if median <= 0:
        return 1.0, "normal(zero-baseline)", 1.0

    ratio = current / median
    if ratio >= 2.0:
        return 0.40, "extreme", ratio
    if ratio >= 1.5:
        return 0.60, "high", ratio
    if ratio >= 1.15:
        return 0.80, "elevated", ratio
    if ratio < 0.85:
        return 1.20, "calm", ratio
    return 1.00, "normal", ratio


def run(**kwargs):
    """
    Dynamic Volatility Position Sizer Task (regime-aware).
    Calculates 14-period ATR across active bot contracts and adjusts lot size
    so that every bot risks equal USD per trade based on its SL percentage,
    scaled by the current volatility regime:
      - vol spike vs baseline -> risk scaled down (up to 0.4x in extreme vol)
      - calm market           -> small boost (1.2x)
    Optionally re-derives sl_pct from ATR (atr_sl_mult * ATR%%) so stops
    breathe with the market.
    """
    target_risk_usd = float(kwargs.get("target_risk_usd", 100.0))
    auto_apply      = bool(kwargs.get("auto_apply",       False))
    atr_sl_mult     = float(kwargs.get("atr_sl_mult",     0.0))   # 0 = keep static sl_pct
    min_sl_pct      = float(kwargs.get("min_sl_pct",      0.5))
    max_sl_pct      = float(kwargs.get("max_sl_pct",      5.0))
    # Notional cap: never let a single position's notional exceed this USD
    # value regardless of what the risk formula suggests (tiny-price coins
    # with near-zero ATR can otherwise explode into thousands of lots).
    max_notional_usd = float(kwargs.get("max_notional_usd", 15.0))

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 3: named column access
        rows = conn.execute(
            "SELECT id, name, symbol, resolution, size, sl_pct "
            "FROM deployments WHERE status='running'"
        ).fetchall()

    if not rows:
        return "ATR Position Sizer: No running deployments to adjust."

    # Fix 1: correct base URL
    client     = DeltaClient(base_url="https://api.india.delta.exchange")
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=5)

    messages = []
    now_str  = datetime.now(timezone.utc).isoformat() + "Z"

    for row in rows:
        dep_id       = row["id"]
        name         = row["name"]
        symbol       = row["symbol"]
        res          = row["resolution"] or "1h"
        current_size = float(row["size"] or 1)
        sl_pct       = float(row["sl_pct"] or 1.5)

        try:
            bars = client.candles(symbol, res, start_time, end_time)
            if not bars or len(bars) < 15:
                messages.append(
                    f"WARN | {name} ({symbol}): insufficient bars "
                    f"({len(bars) if bars else 0}) for ATR calculation"
                )
                continue

            # Fix 2: use dict key access
            close_px = float(bars[-1]["close"])
            atr_val  = _calculate_atr(bars, 14)

            if atr_val <= 0 or close_px <= 0:
                messages.append(
                    f"WARN | {name} ({symbol}): invalid ATR={atr_val:.4f} "
                    f"or close={close_px:.4f}"
                )
                continue

            atr_pct = (atr_val / close_px) * 100.0

            # Regime-aware risk scaling
            regime_mult, regime, ratio = _regime_multiplier(bars, 14, 60)
            eff_risk_usd = target_risk_usd * regime_mult

            # Optional ATR-derived stop-loss (sl breathes with the market)
            eff_sl_pct = sl_pct
            if atr_sl_mult > 0:
                eff_sl_pct = min(max(atr_sl_mult * atr_pct, min_sl_pct), max_sl_pct)

            # Fix 8: include contract_value in risk calculation
            # risk_per_lot = close_px * contract_value * (sl_pct / 100)
            cv           = _get_contract_value(client, symbol)
            risk_per_lot = close_px * cv * (eff_sl_pct / 100.0)

            if risk_per_lot <= 0:
                continue

            # Fix 4: enforce integer lot sizes — Delta does not support fractional lots
            recommended_size = max(1, round(eff_risk_usd / risk_per_lot))

            # Notional cap — hard ceiling on position value
            notional_per_lot = close_px * cv
            if notional_per_lot > 0:
                cap_lots = max(1, int(max_notional_usd / notional_per_lot))
                if recommended_size > cap_lots:
                    recommended_size = cap_lots

            msg = (
                f"{name} ({symbol}): "
                f"size {current_size:.0f} -> {recommended_size} lots "
                f"(ATR={atr_val:.4f} / {atr_pct:.3f}% "
                f"regime={regime} x{regime_mult:.2f} ratio={ratio:.2f} "
                f"sl={eff_sl_pct:.2f}% CV={cv} "
                f"risk_per_lot=${risk_per_lot:.4f} "
                f"eff_target=${eff_risk_usd:.2f})"
            )

            # Fix 5: threshold >= 1 for integer lot comparison
            if auto_apply and (abs(recommended_size - current_size) >= 1
                               or (atr_sl_mult > 0 and abs(eff_sl_pct - sl_pct) >= 0.1)):
                try:
                    with connect() as conn:
                        if atr_sl_mult > 0:
                            conn.execute(
                                "UPDATE deployments SET size=?, sl_pct=? WHERE id=?",
                                (recommended_size, round(eff_sl_pct, 2), dep_id),
                            )
                        else:
                            conn.execute(
                                "UPDATE deployments SET size=? WHERE id=?",
                                (recommended_size, dep_id),
                            )
                    # Fix 6: log audit event
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'atr_position_sizer', ?)",
                            (
                                dep_id, now_str,
                                f"Size adjusted {current_size:.0f} -> {recommended_size} lots, "
                                f"sl_pct {sl_pct:.2f} -> {eff_sl_pct:.2f} "
                                f"(regime={regime} x{regime_mult:.2f} "
                                f"eff_target=${eff_risk_usd:.2f} "
                                f"risk_per_lot=${risk_per_lot:.4f} "
                                f"ATR={atr_val:.4f})",
                            ),
                        )
                    msg += " [Applied]"
                except Exception as e:
                    msg += f" [Apply failed: {e}]"

            messages.append(msg)

        # Fix 7: log errors instead of silently continuing
        except Exception as e:
            messages.append(f"ERR | {name} ({symbol}): {e}")

    if not messages:
        return "ATR Position Sizer: All active bot sizes are aligned with ATR risk targets."

    return "### ATR Position Sizer\n\n" + "\n".join(messages)

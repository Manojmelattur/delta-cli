"""Fear and Greed Monitor Task

Computes a simple crypto fear/greed score (0-100) using on-chain
and market signals available directly from Delta Exchange:

  Signal 1 — Funding Rate Sentiment  (weight 35%)
    Extreme positive funding = greed (longs paying shorts)
    Extreme negative funding = fear  (shorts paying longs)

  Signal 2 — Volatility              (weight 25%)
    High volatility relative to 30d average = fear
    Low  volatility relative to 30d average = greed

  Signal 3 — Price Momentum          (weight 25%)
    Price above 30d SMA = greed
    Price below 30d SMA = fear

  Signal 4 — Open Interest Change    (weight 15%)
    Rising OI + rising price = greed
    Rising OI + falling price = fear

Score interpretation:
  0  - 20  : Extreme Fear
  21 - 40  : Fear
  41 - 60  : Neutral
  61 - 80  : Greed
  81 - 100 : Extreme Greed

The score is written to app_settings for other tasks to read.
Mean-reversion bots are paused in Extreme Fear/Greed zones.

Params (set in task params_json):
    symbols              : Symbols to include in score (default top 5)
    resolution           : Candle resolution (default "1h")
    lookback_days        : History for volatility and momentum (default 30)
    extreme_fear_threshold  : Score below this pauses mean-rev bots (default 20)
    extreme_greed_threshold : Score above this pauses mean-rev bots (default 80)
    auto_pause           : If True, pauses mean-rev bots in extremes (default False)
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.store.db import connect


_BASE_URL          = "https://api.india.delta.exchange"
_FG_KEY            = "market.fear_greed"
_FG_DETAIL_KEY     = "market.fear_greed.detail"

_MEAN_REV_STRATEGIES = {
    "rsi_mr", "bollinger", "vwap", "vwap_reversion",
    "mean_reversion", "rsi_divergence",
}


def _score_to_label(score: float) -> str:
    if score <= 20:  return "Extreme Fear"
    if score <= 40:  return "Fear"
    if score <= 60:  return "Neutral"
    if score <= 80:  return "Greed"
    return "Extreme Greed"


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize a value to 0-100 range."""
    if max_val == min_val:
        return 50.0
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100.0))


def _calc_funding_score(tickers: list) -> tuple:
    """Signal 1: Funding Rate Sentiment.

    Average funding rate across symbols.
    Positive funding = crowd is long = greed.
    Negative funding = crowd is short = fear.

    Returns (score 0-100, detail_str)
    """
    rates = []
    for t in tickers:
        fr = float(t.get("funding_rate") or 0)
        rates.append(fr)

    if not rates:
        return 50.0, "no data"

    avg_fr = sum(rates) / len(rates)
    # Typical funding range: -0.003 to +0.003 per interval
    # Map to 0-100: -0.003 = 0 (extreme fear), +0.003 = 100 (extreme greed)
    score = _normalize(avg_fr, -0.003, 0.003)
    return score, f"avg_funding={avg_fr:.6f}"


def _calc_volatility_score(
    bars_map: Dict[str, list],
    lookback_days: int,
) -> tuple:
    """Signal 2: Volatility relative to 30d average.

    High current volatility vs historical = fear.
    Low  current volatility vs historical = greed.

    Returns (score 0-100, detail_str)
    """
    vol_ratios = []

    for sym, bars in bars_map.items():
        if len(bars) < 48:
            continue

        closes = [float(b.close) for b in bars]

        # Recent volatility: std dev of last 24 bars
        recent = closes[-24:]
        mean_r = sum(recent) / len(recent)
        std_r  = (sum((c - mean_r) ** 2 for c in recent) / len(recent)) ** 0.5
        vol_r  = std_r / mean_r if mean_r > 0 else 0.0

        # Historical volatility: std dev of all bars
        mean_h = sum(closes) / len(closes)
        std_h  = (sum((c - mean_h) ** 2 for c in closes) / len(closes)) ** 0.5
        vol_h  = std_h / mean_h if mean_h > 0 else 0.0

        if vol_h > 0:
            vol_ratios.append(vol_r / vol_h)

    if not vol_ratios:
        return 50.0, "no data"

    avg_ratio = sum(vol_ratios) / len(vol_ratios)
    # ratio > 1 = higher than normal volatility = fear (low score)
    # ratio < 1 = lower than normal volatility  = greed (high score)
    # Map: ratio 0.5 = 75 (greed), ratio 1.0 = 50 (neutral), ratio 2.0 = 0 (fear)
    score = _normalize(avg_ratio, 2.0, 0.5)
    return score, f"avg_vol_ratio={avg_ratio:.4f}"


def _calc_momentum_score(bars_map: Dict[str, list]) -> tuple:
    """Signal 3: Price momentum vs 30d SMA.

    Price above SMA = bullish momentum = greed.
    Price below SMA = bearish momentum = fear.

    Returns (score 0-100, detail_str)
    """
    deviations = []

    for sym, bars in bars_map.items():
        if len(bars) < 20:
            continue

        closes    = [float(b.close) for b in bars]
        sma       = sum(closes) / len(closes)
        last      = closes[-1]
        deviation = (last - sma) / sma if sma > 0 else 0.0
        deviations.append(deviation)

    if not deviations:
        return 50.0, "no data"

    avg_dev = sum(deviations) / len(deviations)
    # Map: -0.10 = 0 (extreme fear), 0 = 50 (neutral), +0.10 = 100 (extreme greed)
    score = _normalize(avg_dev, -0.10, 0.10)
    return score, f"avg_price_vs_sma={avg_dev:+.4f}"


def _calc_oi_score(tickers: list) -> tuple:
    """Signal 4: Open Interest change direction.

    Rising OI + rising price = new longs entering = greed.
    Rising OI + falling price = new shorts entering = fear.

    Uses OI change percentage from ticker data.
    Returns (score 0-100, detail_str)
    """
    oi_signals = []

    for t in tickers:
        oi_change = float(t.get("oi_change_usd_6h") or
                          t.get("oi_value_usd")     or 0)
        price_change = float(t.get("change_24h") or 0)

        if oi_change == 0:
            continue

        # Both rising = greed (100), both falling = neutral (50),
        # OI rising + price falling = fear (0)
        if oi_change > 0 and price_change > 0:
            oi_signals.append(75.0)
        elif oi_change > 0 and price_change < 0:
            oi_signals.append(25.0)
        elif oi_change < 0 and price_change > 0:
            oi_signals.append(60.0)
        else:
            oi_signals.append(40.0)

    if not oi_signals:
        return 50.0, "no data"

    score = sum(oi_signals) / len(oi_signals)
    return score, f"avg_oi_signal={score:.1f}"


def run(**kwargs):
    resolution              = kwargs.get("resolution",              "1h")
    lookback_days           = int(kwargs.get("lookback_days",       30))
    extreme_fear_threshold  = float(kwargs.get("extreme_fear_threshold",  20.0))
    extreme_greed_threshold = float(kwargs.get("extreme_greed_threshold", 80.0))
    auto_pause              = bool(kwargs.get("auto_pause",         False))
    custom_symbols          = kwargs.get("symbols",                 None)

    now_str  = datetime.now(timezone.utc).isoformat() + "Z"
    client   = DeltaClient(base_url=_BASE_URL)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=lookback_days)

    # Resolve symbols
    try:
        tickers = client.tickers(contract_types="perpetual_futures")
        tickers.sort(
            key=lambda x: float(x.get("turnover_usd") or 0),
            reverse=True,
        )
    except Exception as e:
        return f"Fear Greed Monitor: Failed to fetch tickers — {e}"

    if custom_symbols:
        symbols = custom_symbols if isinstance(custom_symbols, list) \
                  else [s.strip() for s in custom_symbols.split(",")]
    else:
        symbols = [t["symbol"] for t in tickers[:5] if t.get("symbol")]

    # Filter tickers to selected symbols
    ticker_map = {t["symbol"]: t for t in tickers}
    sel_tickers = [ticker_map[s] for s in symbols if s in ticker_map]

    # Fetch bars for all symbols
    bars_map: Dict[str, list] = {}
    errors = []

    for sym in symbols:
        try:
            bars = load_history(client, sym, resolution, start_time, end_time)
            if bars and len(bars) >= 20:
                bars_map[sym] = bars
            else:
                errors.append(
                    f"WARN | {sym}: insufficient bars "
                    f"({len(bars) if bars else 0})"
                )
        except Exception as e:
            errors.append(f"ERR | {sym}: {e}")

    if not bars_map and not sel_tickers:
        return (
            "Fear Greed Monitor: No data available to compute score.\n"
            + "\n".join(errors)
        )

    # Calculate each signal
    s1, d1 = _calc_funding_score(sel_tickers)
    s2, d2 = _calc_volatility_score(bars_map, lookback_days)
    s3, d3 = _calc_momentum_score(bars_map)
    s4, d4 = _calc_oi_score(sel_tickers)

    # Weighted composite score
    weights = {
        "funding":    0.35,
        "volatility": 0.25,
        "momentum":   0.25,
        "oi":         0.15,
    }
    composite = (
        s1 * weights["funding"]    +
        s2 * weights["volatility"] +
        s3 * weights["momentum"]   +
        s4 * weights["oi"]
    )
    label = _score_to_label(composite)

    # Persist to app_settings
    detail_payload = json.dumps({
        "score":      round(composite, 2),
        "label":      label,
        "signals": {
            "funding":    {"score": round(s1, 2), "detail": d1, "weight": weights["funding"]},
            "volatility": {"score": round(s2, 2), "detail": d2, "weight": weights["volatility"]},
            "momentum":   {"score": round(s3, 2), "detail": d3, "weight": weights["momentum"]},
            "oi":         {"score": round(s4, 2), "detail": d4, "weight": weights["oi"]},
        },
        "symbols":    symbols,
        "updated_at": now_str,
    })

    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_FG_KEY, json.dumps(round(composite, 2))),
            )
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_FG_DETAIL_KEY, detail_payload),
            )
    except Exception as e:
        errors.append(f"ERR | app_settings write failed — {e}")

    messages = []

    # Auto-pause mean-reversion bots in extreme zones
    is_extreme = (
        composite <= extreme_fear_threshold or
        composite >= extreme_greed_threshold
    )

    if is_extreme and auto_pause:
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join(["?"] * len(_MEAN_REV_STRATEGIES))
            mean_rev_bots = conn.execute(
                f"SELECT id, name, strategy FROM deployments "
                f"WHERE status='running' "
                f"AND strategy IN ({placeholders})",
                tuple(_MEAN_REV_STRATEGIES),
            ).fetchall()

        paused = 0
        for bot in mean_rev_bots:
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (bot["id"],),
                    )
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'fear_greed_monitor', ?)",
                        (
                            bot["id"], now_str,
                            f"Paused — {label} zone "
                            f"(score={composite:.1f}, "
                            f"threshold={extreme_fear_threshold}/{extreme_greed_threshold}). "
                            f"Mean-reversion strategies underperform in extremes.",
                        ),
                    )
                paused += 1
            except Exception as e:
                errors.append(f"ERR | {bot['name']}: pause failed — {e}")

        if paused > 0:
            messages.append(
                f"ACTION: Paused {paused} mean-reversion bots "
                f"in {label} zone (score={composite:.1f})."
            )

    elif is_extreme and not auto_pause:
        messages.append(
            f"WARNING: {label} zone detected (score={composite:.1f}). "
            f"Set auto_pause=true to automatically pause mean-reversion bots."
        )

    # Build report
    bar_count = int(composite / 5)
    bar_str   = "█" * bar_count + "░" * (20 - bar_count)

    lines = [
        "Fear and Greed Monitor",
        f"  Symbols   : {', '.join(symbols)}",
        f"  Lookback  : {lookback_days} days",
        f"  Resolution: {resolution}",
        "",
        f"SCORE: {composite:.1f} / 100  —  {label}",
        f"  [{bar_str}]",
        "",
        "Signal Breakdown:",
        f"  {'Signal':>12} {'Score':>7} {'Weight':>8}  Detail",
        "  " + "-" * 55,
        f"  {'Funding':>12} {s1:>7.1f} {weights['funding']*100:>7.0f}%  {d1}",
        f"  {'Volatility':>12} {s2:>7.1f} {weights['volatility']*100:>7.0f}%  {d2}",
        f"  {'Momentum':>12} {s3:>7.1f} {weights['momentum']*100:>7.0f}%  {d3}",
        f"  {'OI Change':>12} {s4:>7.1f} {weights['oi']*100:>7.0f}%  {d4}",
        "",
        "Score Guide:",
        "  0-20  Extreme Fear  |  21-40 Fear  |  41-60 Neutral",
        "  61-80 Greed         |  81-100 Extreme Greed",
        "",
        f"Score written to app_settings key='{_FG_KEY}'.",
    ]

    if messages:
        lines.append("")
        lines.extend(messages)

    if errors:
        lines.append("")
        lines.append("Warnings/Errors:")
        lines.extend(f"  {e}" for e in errors)

    return "### Fear and Greed Monitor\n\n" + "\n".join(lines)

"""Market Regime Detector Task

Calculates ADX (trend strength) and Bollinger Band width (volatility)
across top symbols to classify the current market as:

  TRENDING   — ADX > adx_threshold (strong directional move)
  VOLATILE   — BB width > bb_width_threshold (wide bands, choppy)
  RANGING    — ADX low + BB width low (tight, mean-reverting)

The detected regime is written to app_settings so other tasks
and strategies can read it without re-calculating.

Other tasks that benefit from regime awareness:
  - atr_risk_manager    : widen stops in VOLATILE regime
  - strategy_retirement : expect lower win rates in VOLATILE
  - auto-deploy tasks   : prefer trend strategies in TRENDING,
                          mean-reversion in RANGING

Params (set in task params_json):
    symbols              : List of symbols to scan (default top 10 by turnover)
    resolution           : Candle resolution for regime detection (default "1h")
    lookback_days        : History window for calculations (default 14)
    adx_period           : ADX calculation period (default 14)
    bb_period            : Bollinger Band period (default 20)
    bb_std               : Bollinger Band standard deviation multiplier (default 2.0)
    adx_threshold        : ADX above this = TRENDING (default 25.0)
    bb_width_threshold   : BB width above this % = VOLATILE (default 4.0)
"""
import sqlite3
import json
import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict

from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.store.db import connect


_BASE_URL = "https://api.india.delta.exchange"

_REGIME_KEY = "market.regime"
_REGIME_DETAIL_KEY = "market.regime.detail"


# ------------------------------------------------------------------
# Technical Indicator Calculations
# ------------------------------------------------------------------

def _calc_adx(bars: list, period: int = 14) -> float:
    """Calculate Average Directional Index (ADX) using Wilder's method.

    ADX measures trend strength regardless of direction.
    ADX > 25 = trending, ADX < 20 = ranging/weak trend.

    Returns 0.0 if not enough bars.
    """
    if len(bars) < period * 2 + 1:
        return 0.0

    plus_dm  = []
    minus_dm = []
    tr_list  = []

    for i in range(1, len(bars)):
        high       = float(bars[i]["high"])
        low        = float(bars[i]["low"])
        prev_high  = float(bars[i - 1]["high"])
        prev_low   = float(bars[i - 1]["low"])
        prev_close = float(bars[i - 1]["close"])

        # True Range
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low  - prev_close),
        )
        tr_list.append(tr)

        # Directional Movement
        up_move   = high - prev_high
        down_move = prev_low - low

        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
            minus_dm.append(0.0)
        elif down_move > up_move and down_move > 0:
            plus_dm.append(0.0)
            minus_dm.append(down_move)
        else:
            plus_dm.append(0.0)
            minus_dm.append(0.0)

    # Wilder smoothing
    def _wilder_smooth(values: list, n: int) -> list:
        if len(values) < n:
            return []
        smoothed = [sum(values[:n])]
        for v in values[n:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / n + v)
        return smoothed

    atr_s    = _wilder_smooth(tr_list,   period)
    plus_s   = _wilder_smooth(plus_dm,   period)
    minus_s  = _wilder_smooth(minus_dm,  period)

    if not atr_s:
        return 0.0

    dx_list = []
    for i in range(len(atr_s)):
        atr_v   = atr_s[i]
        if atr_v == 0:
            continue
        plus_di  = 100 * plus_s[i]  / atr_v
        minus_di = 100 * minus_s[i] / atr_v
        di_sum   = plus_di + minus_di
        if di_sum == 0:
            continue
        dx = 100 * abs(plus_di - minus_di) / di_sum
        dx_list.append(dx)

    if not dx_list:
        return 0.0

    # ADX = Wilder smooth of DX
    adx_s = _wilder_smooth(dx_list, period)
    return adx_s[-1] if adx_s else 0.0


def _calc_bb_width_pct(bars: list, period: int = 20, std_mult: float = 2.0) -> float:
    """Calculate Bollinger Band width as a percentage of the middle band.

    BB Width % = (Upper - Lower) / Middle * 100

    High BB width = volatile/expanding market
    Low  BB width = contracting/ranging market

    Returns 0.0 if not enough bars.
    """
    if len(bars) < period:
        return 0.0

    closes = [float(b["close"]) for b in bars[-period:]]
    mean   = sum(closes) / period
    std    = (sum((c - mean) ** 2 for c in closes) / period) ** 0.5

    upper  = mean + std_mult * std
    lower  = mean - std_mult * std

    if mean == 0:
        return 0.0

    return (upper - lower) / mean * 100.0


def _classify_regime(adx: float, bb_width: float,
                     adx_threshold: float, bb_width_threshold: float) -> str:
    """Classify market regime from ADX and BB width."""
    if adx >= adx_threshold:
        return "TRENDING"
    if bb_width >= bb_width_threshold:
        return "VOLATILE"
    return "RANGING"


# ------------------------------------------------------------------
# Main Task
# ------------------------------------------------------------------

def run(**kwargs):
    resolution        = kwargs.get("resolution",         "1h")
    lookback_days     = int(kwargs.get("lookback_days",  14))
    adx_period        = int(kwargs.get("adx_period",     14))
    bb_period         = int(kwargs.get("bb_period",      20))
    bb_std            = float(kwargs.get("bb_std",       2.0))
    adx_threshold     = float(kwargs.get("adx_threshold",     25.0))
    bb_width_threshold= float(kwargs.get("bb_width_threshold", 4.0))
    custom_symbols    = kwargs.get("symbols",            None)

    now_str = datetime.now(timezone.utc).isoformat() + "Z"

    client   = DeltaClient(base_url=_BASE_URL)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=lookback_days)

    # Resolve symbol list
    if custom_symbols:
        symbols = custom_symbols if isinstance(custom_symbols, list) \
                  else [s.strip() for s in custom_symbols.split(",")]
    else:
        try:
            tickers = client.tickers(contract_types="perpetual_futures")
            tickers.sort(
                key=lambda x: float(x.get("turnover_usd") or 0),
                reverse=True,
            )
            symbols = [t["symbol"] for t in tickers[:10] if t.get("symbol")]
        except Exception as e:
            return f"Regime Detector: Failed to fetch tickers — {e}"

    if not symbols:
        return "Regime Detector: No symbols to analyse."

    # Calculate regime per symbol
    symbol_regimes: Dict[str, dict] = {}
    errors = []

    for sym in symbols:
        try:
            bars = load_history(client, sym, resolution, start_time, end_time)
            if not bars or len(bars) < max(adx_period * 2 + 1, bb_period):
                errors.append(
                    f"WARN | {sym}: insufficient bars ({len(bars) if bars else 0})"
                )
                continue

            # Convert Bar objects to dicts for indicator functions
            bar_dicts = [
                {
                    "high":  float(b.high),
                    "low":   float(b.low),
                    "close": float(b.close),
                    "open":  float(b.open),
                }
                for b in bars
            ]

            adx      = _calc_adx(bar_dicts, adx_period)
            bb_width = _calc_bb_width_pct(bar_dicts, bb_period, bb_std)
            regime   = _classify_regime(
                adx, bb_width, adx_threshold, bb_width_threshold
            )

            symbol_regimes[sym] = {
                "symbol":   sym,
                "regime":   regime,
                "adx":      round(adx,      2),
                "bb_width": round(bb_width, 4),
            }

        except Exception as e:
            errors.append(f"ERR | {sym}: {e}")

    if not symbol_regimes:
        return (
            "Regime Detector: Could not calculate regime for any symbol.\n"
            + "\n".join(errors)
        )

    # Determine dominant regime by majority vote
    regime_counts: Dict[str, int] = {"TRENDING": 0, "VOLATILE": 0, "RANGING": 0}
    for sr in symbol_regimes.values():
        regime_counts[sr["regime"]] = regime_counts.get(sr["regime"], 0) + 1

    dominant_regime = max(regime_counts, key=lambda x: regime_counts[x])

    # Persist regime to app_settings for other tasks to read
    detail_payload = json.dumps({
        "regime":        dominant_regime,
        "counts":        regime_counts,
        "symbols":       symbol_regimes,
        "updated_at":    now_str,
        "resolution":    resolution,
        "adx_threshold": adx_threshold,
        "bb_threshold":  bb_width_threshold,
    })

    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_REGIME_KEY, json.dumps(dominant_regime)),
            )
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_REGIME_DETAIL_KEY, detail_payload),
            )
    except Exception as e:
        errors.append(f"ERR | app_settings write failed — {e}")

    # Build report
    lines = [
        "Market Regime Detector",
        f"  Resolution : {resolution}",
        f"  Lookback   : {lookback_days} days",
        f"  Symbols    : {len(symbol_regimes)} analysed",
        f"  ADX thresh : {adx_threshold}",
        f"  BB thresh  : {bb_width_threshold}%",
        "",
        f"DOMINANT REGIME: {dominant_regime}",
        f"  TRENDING : {regime_counts['TRENDING']} symbols",
        f"  VOLATILE : {regime_counts['VOLATILE']} symbols",
        f"  RANGING  : {regime_counts['RANGING']} symbols",
        "",
        "Per-Symbol Breakdown:",
        f"  {'Symbol':>10} {'Regime':>10} {'ADX':>8} {'BB Width%':>10}",
        "  " + "-" * 44,
    ]

    for sym, sr in sorted(
        symbol_regimes.items(),
        key=lambda x: x[1]["adx"],
        reverse=True,
    ):
        lines.append(
            f"  {sym:>10} {sr['regime']:>10} "
            f"{sr['adx']:>8.2f} {sr['bb_width']:>9.4f}%"
        )

    lines.append("")
    lines.append(
        f"Regime written to app_settings key='{_REGIME_KEY}'. "
        f"Other tasks can read it with: "
        f"SELECT value_json FROM app_settings WHERE key='{_REGIME_KEY}'"
    )

    if errors:
        lines.append("")
        lines.append("Warnings/Errors:")
        lines.extend(f"  {e}" for e in errors)

    return "### Market Regime Detector\n\n" + "\n".join(lines)

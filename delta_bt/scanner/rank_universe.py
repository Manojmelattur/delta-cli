"""Universe scanner — rank tradable perps by liquidity + regime + volatility.

Pulls Delta's live tickers, filters by 24h USD turnover, then for each
survivor loads recent candles and computes:

  * ADX(14)         — trend strength
  * ATR% (of close) — realized bar-range vol
  * Bollinger width % (20,2) percentile over lookback — squeeze detector
  * return over lookback vs BTCUSD                     — relative strength
  * abs(funding_rate) and open_interest (from tickers)

A composite z-score ranks the survivors. Optional --regime {trend,range}
biases weights so the shortlist matches the strategies you plan to run.
"""
from __future__ import annotations

import csv
import math
import os
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from ..core.indicators import ADX
from ..data.delta_client import DeltaClient
from ..data.history import load_history


@dataclass
class SymbolScore:
    symbol: str
    price: float
    turnover_usd: float
    open_interest: float
    funding_pct: float          # absolute funding rate, %
    adx: Optional[float]
    atr_pct: Optional[float]    # ATR / close, %
    bb_width_pct: Optional[float]
    ret_pct: Optional[float]    # % change over lookback bars
    rs_vs_btc: Optional[float]  # ret_pct - btc_ret_pct
    regime: str                 # "trend" | "range" | "unknown"
    score: float = 0.0
    reason: str = ""


# ---------------------------------------------------------------- helpers

def _atr_pct(bars, n: int = 14) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        b, p = bars[i], bars[i - 1]
        trs.append(max(b.high - b.low,
                       abs(b.high - p.close),
                       abs(b.low - p.close)))
    atr = sum(trs[-n:]) / n
    close = bars[-1].close
    return (atr / close) * 100.0 if close else None


def _bb_width_pct(bars, n: int = 20) -> Optional[float]:
    if len(bars) < n:
        return None
    closes = [b.close for b in bars[-n:]]
    mu = sum(closes) / n
    sd = statistics.pstdev(closes)
    if not mu:
        return None
    return (4.0 * sd / mu) * 100.0  # (upper - lower) / mid, with 2σ bands


def _ret_pct(bars, lookback: int) -> Optional[float]:
    if len(bars) < lookback + 1:
        return None
    a, b = bars[-lookback - 1].close, bars[-1].close
    return ((b - a) / a) * 100.0 if a else None


def _adx_final(bars, period: int = 14) -> Optional[float]:
    adx = ADX(period)
    last = None
    for b in bars:
        v = adx.update(b)
        if v is not None:
            last = v
    return last


def _regime_of(adx: Optional[float], trend_min: float, range_max: float) -> str:
    if adx is None:
        return "unknown"
    if adx >= trend_min:
        return "trend"
    if adx < range_max:
        return "range"
    return "unknown"


def _zscore(vals: List[float]) -> List[float]:
    xs = [v for v in vals if v is not None and not math.isnan(v)]
    if len(xs) < 2:
        return [0.0 for _ in vals]
    mu = sum(xs) / len(xs)
    sd = statistics.pstdev(xs) or 1.0
    return [((v - mu) / sd) if (v is not None and not math.isnan(v)) else 0.0
            for v in vals]


# ---------------------------------------------------------------- per-symbol

def _score_symbol(client: DeltaClient, ticker: dict, resolution: str,
                  lookback_bars: int, adx_len: int,
                  trend_min: float, range_max: float) -> Optional[SymbolScore]:
    sym = ticker.get("symbol")
    if not sym:
        return None
    price = float(ticker.get("close") or ticker.get("mark_price") or 0)
    turnover = float(ticker.get("turnover_usd") or ticker.get("turnover") or 0)
    oi = float(ticker.get("open_interest") or 0)
    funding = abs(float(ticker.get("funding_rate") or 0))

    # pull just enough history to compute the indicators
    step_sec = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}.get(resolution, 900)
    end = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
    # Ensure at least 150 bars for ADX warmup, independent of lookback
    needed_bars = max(lookback_bars, 150) + adx_len + 5
    start = end - timedelta(seconds=step_sec * needed_bars)
    try:
        bars = load_history(client, sym, resolution, start, end)
    except Exception as e:
        return SymbolScore(sym, price, turnover, oi, funding,
                           None, None, None, None, None, "unknown",
                           reason=f"history_error: {e}")
    if len(bars) < adx_len + 5:
        return SymbolScore(sym, price, turnover, oi, funding,
                           None, None, None, None, None, "unknown",
                           reason="insufficient_history")

    adx = _adx_final(bars, adx_len)
    atrp = _atr_pct(bars, adx_len)
    bbw = _bb_width_pct(bars)
    ret = _ret_pct(bars, min(lookback_bars, len(bars) - 1))
    return SymbolScore(
        sym, price, turnover, oi, funding,
        adx, atrp, bbw, ret, None,
        regime=_regime_of(adx, trend_min, range_max),
    )


# ---------------------------------------------------------------- public API

def rank_universe(
    client: DeltaClient,
    *,
    resolution: str = "1h",
    lookback_bars: int = 168,          # ~1 week on 1h
    adx_len: int = 14,
    trend_min: float = 25.0,
    range_max: float = 20.0,
    min_turnover_usd: float = 20_000_000.0,
    max_funding_pct: float = 0.05,     # absolute, %
    atr_min_pct: float = 0.5,
    atr_max_pct: float = 8.0,
    quote_symbol_suffix: str = "USD",
    contract_types: str = "perpetual_futures",
    regime_bias: str = "any",          # "trend" | "range" | "any"
    top: int = 20,
    workers: int = 8,
) -> List[SymbolScore]:
    """Return ranked SymbolScore list, best first."""
    tickers = client.tickers(contract_types=contract_types)

    # -- pre-filter on cheap fields (no history yet) --
    universe: List[dict] = []
    for t in tickers:
        sym = t.get("symbol") or ""
        if quote_symbol_suffix and not sym.endswith(quote_symbol_suffix):
            continue
        turnover = float(t.get("turnover_usd") or t.get("turnover") or 0)
        if turnover < min_turnover_usd:
            continue
        funding = abs(float(t.get("funding_rate") or 0))
        if funding > max_funding_pct:
            continue
        universe.append(t)

    if not universe:
        return []

    # -- per-symbol metrics (parallel history pulls) --
    scored: List[SymbolScore] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_score_symbol, client, t, resolution,
                          lookback_bars, adx_len, trend_min, range_max)
                for t in universe]
        for f in as_completed(futs):
            s = f.result()
            if s is not None:
                scored.append(s)

    # -- attach relative strength vs BTCUSD --
    btc = next((s for s in scored if s.symbol == "BTCUSD"), None)
    btc_ret = btc.ret_pct if btc and btc.ret_pct is not None else 0.0
    for s in scored:
        if s.ret_pct is not None:
            s.rs_vs_btc = s.ret_pct - btc_ret

    # -- volatility band filter --
    def in_band(x): return x is not None and atr_min_pct <= x <= atr_max_pct
    scored = [s for s in scored if in_band(s.atr_pct)]
    if not scored:
        return []

    # -- composite z-score --
    z_turn = _zscore([math.log10(max(s.turnover_usd, 1)) for s in scored])
    z_adx  = _zscore([s.adx if s.adx is not None else 0.0 for s in scored])
    z_atr  = _zscore([s.atr_pct or 0.0 for s in scored])
    z_bb   = _zscore([-(s.bb_width_pct or 0.0) for s in scored])  # squeeze = higher score
    z_rs   = _zscore([abs(s.rs_vs_btc) if s.rs_vs_btc is not None else 0.0
                      for s in scored])
    z_fund = _zscore([-s.funding_pct for s in scored])            # calmer funding = better

    if regime_bias == "trend":
        w = dict(turn=0.8, adx=1.4, atr=0.9, bb=0.2, rs=1.1, fund=0.3)
    elif regime_bias == "range":
        w = dict(turn=0.8, adx=-0.6, atr=0.4, bb=1.2, rs=0.2, fund=0.5)
    else:
        w = dict(turn=1.0, adx=0.7, atr=0.7, bb=0.6, rs=0.7, fund=0.4)

    for i, s in enumerate(scored):
        s.score = (w["turn"] * z_turn[i] + w["adx"] * z_adx[i]
                   + w["atr"] * z_atr[i] + w["bb"] * z_bb[i]
                   + w["rs"] * z_rs[i] + w["fund"] * z_fund[i])

    if regime_bias in ("trend", "range"):
        scored = [s for s in scored if s.regime in (regime_bias, "unknown")]

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top] if top and top > 0 else scored


def write_universe_csv(rows: List[SymbolScore], path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = ["rank", "symbol", "score", "regime", "price",
            "turnover_usd", "open_interest", "funding_pct",
            "adx", "atr_pct", "bb_width_pct", "ret_pct", "rs_vs_btc",
            "reason"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, s in enumerate(rows, 1):
            d = asdict(s)
            d["rank"] = i
            w.writerow([d.get(c, "") for c in cols])
    return path

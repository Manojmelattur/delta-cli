"""Tests for the tail-window logic that prevents stale signals from firing.

This mirrors the logic in delta_bt/scheduler.py::_evaluate() without needing a
real database or live market data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from delta_bt.core.registry import load_strategy
from delta_bt.core.strategy import StrategyContext
from delta_bt.core.types import Bar, Position, Signal


TAIL_ONLY_STRATEGIES = {
    "price_action_pinbar", "price_action_engulfing",
    "fvg", "smc_ob", "smc_ob_fvg", "smc_liquidity_sweep",
    "macd_divergence", "rsi_divergence",
    "bollinger", "rsi_mr", "vwap",
}

TAIL_BY_RES = {
    "1m": 3, "3m": 3, "5m": 3,
    "15m": 4, "30m": 4,
    "1h": 6, "2h": 6,
    "4h": 8, "6h": 8,
    "1d": 10, "7d": 10,
}

RANGE_TAIL_BY_RES = {
    "1m": 1, "3m": 1, "5m": 1,
    "15m": 1, "30m": 1,
    "1h": 2, "2h": 2,
    "4h": 3, "6h": 3,
    "1d": 4, "7d": 4,
}


def _make_bars(symbol: str = "BTCUSD", resolution: str = "15m", n: int = 40) -> List[Bar]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        c = 100 + i * 0.1
        o = c - 0.05
        bars.append(Bar(
            ts=base + timedelta(minutes=15 * i),
            open=o,
            high=o + 0.1,
            low=o - 0.05,
            close=c,
            volume=1,
            symbol=symbol,
            resolution=resolution,
        ))
    return bars


def _bar(close: float, i: int = 0, resolution: str = "1h") -> Bar:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
    return Bar(
        ts=ts, open=close, high=close + 0.1, low=close - 0.1,
        close=close, volume=1, symbol="BTCUSD", resolution=resolution,
    )


def evaluate_signal(name: str, params: dict, bars: List[Bar]) -> tuple:
    """Replicate the signal-discovery part of _evaluate()."""
    strat = load_strategy(name, params)
    if hasattr(strat, "on_start"):
        strat.on_start()
    pos = Position(symbol=bars[0].symbol)
    ctx = StrategyContext(pos, 0.0, 0.0)
    strat_regime = getattr(strat, "regime", None) or getattr(type(strat), "regime", "any")
    tail_only = strat_regime == "range" or name in TAIL_ONLY_STRATEGIES
    tail = (RANGE_TAIL_BY_RES.get(bars[0].resolution, 1) if tail_only
            else TAIL_BY_RES.get(bars[0].resolution, 3))
    tail_sig = None
    latest_sig = None
    n = len(bars)
    for i, bar in enumerate(bars):
        sig = strat.on_bar(bar, ctx)
        sname = sig.name if isinstance(sig, Signal) else str(sig)
        if sname in ("BUY", "SELL"):
            latest_sig = sname
            if i >= n - tail:
                tail_sig = sname
    return tail_sig, latest_sig, tail_only, tail


def _filter(n: int, resolution: str, regime: str, tail_only: bool, signal_at: int, signal: str):
    """Reimplement the tail-window filter with a synthetic signal source."""
    is_tail_only = regime == "range" or tail_only
    tail = (RANGE_TAIL_BY_RES.get(resolution, 1) if is_tail_only
            else TAIL_BY_RES.get(resolution, 3))
    tail_sig = None
    latest_sig = None
    for i in range(n):
        s = signal if i == signal_at else "HOLD"
        if s in ("BUY", "SELL"):
            latest_sig = s
            if i >= n - tail:
                tail_sig = s
    return tail_sig, latest_sig, is_tail_only, tail


def test_tail_only_strategy_ignores_stale_signal():
    # Signal 10 bars back; range strategy with tail=1 must ignore it.
    tail_sig, latest_sig, tail_only, tail = _filter(
        n=40, resolution="15m", regime="range", tail_only=True,
        signal_at=30, signal="BUY",
    )
    assert tail_only is True
    assert tail == 1
    assert tail_sig is None
    assert latest_sig == "BUY"


def test_tail_only_strategy_accepts_signal_on_last_bar():
    tail_sig, _, _, _ = _filter(
        n=40, resolution="15m", regime="range", tail_only=True,
        signal_at=39, signal="BUY",
    )
    assert tail_sig == "BUY"


def test_trend_strategy_can_use_wider_tail():
    tail_sig, latest_sig, tail_only, tail = _filter(
        n=40, resolution="15m", regime="trend", tail_only=False,
        signal_at=37, signal="BUY",
    )
    assert tail_only is False
    assert tail == 4
    assert tail_sig == "BUY"
    assert latest_sig == "BUY"


def test_trend_strategy_ignores_signal_beyond_tail():
    tail_sig, latest_sig, _, _ = _filter(
        n=40, resolution="15m", regime="trend", tail_only=False,
        signal_at=5, signal="SELL",
    )
    assert tail_sig is None
    assert latest_sig == "SELL"


def test_tail_window_scales_with_resolution():
    assert TAIL_BY_RES["1m"] == 3
    assert TAIL_BY_RES["15m"] == 4
    assert TAIL_BY_RES["1h"] == 6
    assert TAIL_BY_RES["1d"] == 10


def test_bollinger_intent_stays_valid_until_middle_band():
    strat = load_strategy("bollinger", {"period": 5, "stdev": 1, "mode": "revert"})
    strat.on_start()
    ctx = StrategyContext(Position(symbol="BTCUSD"), 0.0, 0.0)
    for i, close in enumerate([100, 100, 100, 100, 96, 98]):
        strat.on_bar(_bar(close, i), ctx)
    assert strat.intent(_bar(98, 6)) == Signal.BUY


def test_rsi_mr_intent_stays_valid_until_midline_exit():
    strat = load_strategy("rsi_mr", {"period": 3, "oversold": 30, "overbought": 70})
    strat.on_start()
    ctx = StrategyContext(Position(symbol="BTCUSD"), 0.0, 0.0)
    for i, close in enumerate([100, 96, 92, 90, 91]):
        strat.on_bar(_bar(close, i), ctx)
    assert strat.intent(_bar(91, 5)) == Signal.BUY

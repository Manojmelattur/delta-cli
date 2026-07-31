"""Shared fixtures for the delta_bt test suite."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from delta_bt.core.registry import load_strategy
from delta_bt.core.strategy import StrategyContext
from delta_bt.core.types import Bar, Position, Signal


HERE = Path(__file__).resolve().parent
FIXTURES_DIR = HERE / "fixtures"


def load_bars_json(name: str) -> List[Bar]:
    raw = json.loads((FIXTURES_DIR / "bars.json").read_text())
    rows = raw[name]
    out = []
    for r in rows:
        ts = datetime.fromisoformat(r["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        out.append(Bar(
            ts=ts,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r.get("volume", 0)),
            symbol=r.get("symbol", "BTCUSD"),
            resolution=r.get("resolution", "15m"),
        ))
    return out


def run_strategy(name: str, params: Dict[str, Any], bars: List[Bar]) -> List[str]:
    """Run a strategy over a list of bars and return the per-bar signal names."""
    strat = load_strategy(name, params)
    if hasattr(strat, "on_start"):
        strat.on_start()
    pos = Position(symbol=bars[0].symbol if bars else "BTCUSD")
    ctx = StrategyContext(pos, 0.0, 0.0)
    signals = []
    for bar in bars:
        sig = strat.on_bar(bar, ctx)
        signals.append(sig.name if isinstance(sig, Signal) else str(sig))
    if hasattr(strat, "on_stop"):
        strat.on_stop()
    return signals


def last_actionable(signals: List[str]) -> str:
    """Return the last BUY/SELL/FLAT signal, or HOLD if none."""
    for s in reversed(signals):
        if s in ("BUY", "SELL", "FLAT"):
            return s
    return "HOLD"


@pytest.fixture
def manifest() -> Dict[str, Any]:
    root = HERE.parent.parent.parent
    return json.loads((root / "strategy_manifest.json").read_text())


@pytest.fixture
def all_bars() -> Dict[str, List[Bar]]:
    raw = json.loads((FIXTURES_DIR / "bars.json").read_text())
    result = {}
    for key, rows in raw.items():
        bars = []
        for r in rows:
            ts = datetime.fromisoformat(r["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bars.append(Bar(
                ts=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume", 0)),
                symbol=r.get("symbol", "BTCUSD"),
                resolution=r.get("resolution", "15m"),
            ))
        result[key] = bars
    return result

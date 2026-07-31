"""Generate shared OHLCV fixtures and export them to JSON.

Output files:
- python/delta_bt/tests/fixtures/bars.json
- src/lib/strategies/__tests__/fixtures/bars.json

Both test suites load the same data so parity tests are comparing apples to apples.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from math import sin
from pathlib import Path
from typing import Any, Dict, List


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
PY_OUT = ROOT / "python" / "delta_bt" / "tests" / "fixtures"
TS_OUT = ROOT / "tests" / "strategies" / "fixtures"


def _bar(ts: datetime, open: float, high: float, low: float, close: float, volume: float = 1.0) -> Dict[str, Any]:
    return {
        "ts": ts.isoformat(),
        "open": open,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "symbol": "BTCUSD",
        "resolution": "15m",
    }


def _trend_up() -> List[Dict[str, Any]]:
    """Sharp downtrend, flat base, huge bullish candle, then steep uptrend. Trend/supertrend fire BUY."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(100):
        if i < 35:
            price = 100 - i * 0.4  # clear downtrend
            noise = (i % 3) * 0.3
            o = price - 0.5 + noise
            c = price + 0.5 + noise
            h = max(o, c) + 0.6
            l = min(o, c) - 0.6
        elif i < 45:
            price = 86.0  # flat base
            noise = (i % 3) * 0.3
            o = price - 0.5 + noise
            c = price + 0.5 + noise
            h = max(o, c) + 0.6
            l = min(o, c) - 0.6
        elif i == 45:
            # huge breakout candle that breaks the supertrend band
            o = 86.0
            c = 180.0
            h = 182.0
            l = 78.0
            price = c
        else:
            price = 180.0 + (i - 45) * 10.0  # steep uptrend
            noise = (i % 3) * 0.3
            o = price - 0.5 + noise
            c = price + 0.5 + noise
            h = max(o, c) + 0.6
            l = min(o, c) - 0.6
        bars.append(_bar(base + timedelta(minutes=15 * i), o, h, l, c, 100 + i))
    return bars


def _trend_down() -> List[Dict[str, Any]]:
    """Sharp uptrend, flat top, huge bearish candle, then steep downtrend. Trend/supertrend fire SELL."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(100):
        if i < 35:
            price = 100 + i * 0.4  # clear uptrend
            noise = (i % 3) * 0.3
            o = price + 0.5 + noise
            c = price - 0.5 + noise
            h = max(o, c) + 0.6
            l = min(o, c) - 0.6
        elif i < 45:
            price = 114.0  # flat top
            noise = (i % 3) * 0.3
            o = price + 0.5 + noise
            c = price - 0.5 + noise
            h = max(o, c) + 0.6
            l = min(o, c) - 0.6
        elif i == 45:
            # huge breakdown candle
            o = 114.0
            c = 30.0
            h = 116.0
            l = 28.0
            price = c
        else:
            price = 30.0 - (i - 45) * 10.0  # steep downtrend
            noise = (i % 3) * 0.3
            o = price + 0.5 + noise
            c = price - 0.5 + noise
            h = max(o, c) + 0.6
            l = min(o, c) - 0.6
        bars.append(_bar(base + timedelta(minutes=15 * i), o, h, l, c, 100 + i))
    return bars


def _range() -> List[Dict[str, Any]]:
    """Sideways price oscillating around a mean. Range strategies should catch reversals."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(80):
        x = i * 0.55
        mid = 100.0
        o = mid + 6 * sin(x)
        c = mid + 6 * sin(x + 1.0)
        h = max(o, c) + 1.5
        l = min(o, c) - 1.5
        v = 100 + i
        bars.append(_bar(base + timedelta(minutes=15 * i), o, h, l, c, v))
    return bars


def _bollinger_touch() -> List[Dict[str, Any]]:
    """Price dips below lower Bollinger band then reverts to mean."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    center = 100
    for i in range(40):
        if i < 30:
            c = center + (i - 15) * 0.2
        elif i == 30:
            c = center - 5.5
        elif i == 31:
            c = center - 5.0
        elif i == 32:
            c = center - 1.0
        else:
            c = center + (i - 32) * 0.2
        o = c + (0.5 if i % 2 else -0.5)
        h = max(o, c) + 0.8
        l = min(o, c) - 0.8
        bars.append(_bar(base + timedelta(minutes=15 * i), o, h, l, c, 100))
    return bars


def _pinbar_rejection() -> List[Dict[str, Any]]:
    """A bearish pinbar at the top of an extended EMA move."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(40):
        if i < 35:
            c = 100 + i * 0.5
        elif i == 35:
            o = 117.5
            h = 120.0
            l = 116.0
            c = 117.0
        elif i == 36:
            c = 116.5
        else:
            c = 116 - (i - 36) * 0.4
        if i != 35:
            o = c + (0.2 if i % 2 else -0.2)
            h = max(o, c) + 0.5
            l = min(o, c) - 0.5
        bars.append(_bar(base + timedelta(minutes=15 * i), o, h, l, c, 100))
    return bars


def _engulfing() -> List[Dict[str, Any]]:
    """A bullish engulfing candle after a short downtrend."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(40):
        if i < 35:
            c = 100 - i * 0.2
        elif i == 35:
            o = 93.0
            c = 92.5
        elif i == 36:
            o = 92.5
            c = 95.0
        else:
            c = 95 + (i - 36) * 0.3
        if i not in (35, 36):
            o = c + (0.2 if i % 2 else -0.2)
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        bars.append(_bar(base + timedelta(minutes=15 * i), o, h, l, c, 100))
    return bars


def main() -> None:
    fixtures = {
        "trend_up": _trend_up(),
        "trend_down": _trend_down(),
        "range": _range(),
        "bollinger_touch": _bollinger_touch(),
        "pinbar_rejection": _pinbar_rejection(),
        "engulfing": _engulfing(),
    }
    PY_OUT.mkdir(parents=True, exist_ok=True)
    TS_OUT.mkdir(parents=True, exist_ok=True)
    for out in (PY_OUT, TS_OUT):
        (out / "bars.json").write_text(json.dumps(fixtures, indent=2))
    print(f"Exported fixtures to {PY_OUT} and {TS_OUT}")


if __name__ == "__main__":
    main()

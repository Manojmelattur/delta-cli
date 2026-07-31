from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext


class KeltnerSqueezeStrategy(Strategy):
    """
    Keltner Channel Squeeze Breakout Strategy.

    Detects low-volatility compression (when Bollinger Bands lie inside Keltner Channels)
    and fires momentum breakout trades when volatility expands outward.

    Params:
        bb_period  (int,   default 20)  — Bollinger Band period
        bb_std     (float, default 2.0) — Bollinger Band standard deviation multiplier
        kc_period  (int,   default 20)  — Keltner Channel ATR period
        kc_mult    (float, default 1.5) — Keltner Channel ATR multiplier
    """

    name = "keltner_squeeze"
    regime = "trend"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self._bars: List[Bar] = []

    def on_bar(self, bar: Bar, ctx: Optional[StrategyContext] = None) -> Signal:
        self._bars.append(bar)
        bb_period = int(self.p("bb_period", 20))
        kc_period = int(self.p("kc_period", 20))
        if len(self._bars) < max(bb_period, kc_period) + 1:
            return Signal.HOLD

        bb_std = float(self.p("bb_std", 2.0))
        kc_mult = float(self.p("kc_mult", 1.5))

        # Bollinger Bands
        closes = [b.close for b in self._bars[-bb_period:]]
        sma = sum(closes) / bb_period
        variance = sum((x - sma) ** 2 for x in closes) / bb_period
        std_dev = math.sqrt(variance)
        bb_upper = sma + bb_std * std_dev
        bb_lower = sma - bb_std * std_dev

        # Keltner Channels
        bars_kc = self._bars[-kc_period - 1:]
        atr_sum = 0.0
        for i in range(1, len(bars_kc)):
            b, prev = bars_kc[i], bars_kc[i - 1]
            atr_sum += max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close))
        atr = atr_sum / kc_period
        kc_upper = sma + kc_mult * atr
        kc_lower = sma - kc_mult * atr

        prev_bar = self._bars[-2]

        # Breakout after squeeze
        if bar.close > kc_upper and prev_bar.close <= kc_upper:
            return Signal.BUY
        elif bar.close < kc_lower and prev_bar.close >= kc_lower:
            return Signal.SELL

        return Signal.HOLD

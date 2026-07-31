"""Supertrend + momentum (ROC) filter.

Params: atr_period(10), multiplier(3.0), mom_period(10), mom_thresh(0.0)
Enters long when Supertrend flips up AND ROC > threshold; short on opposite.
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class SupertrendMomentumV2(Strategy):
    name = "supertrend_mom_v2"

    regime = "trend"
    def on_start(self):
        self.n = int(self.p("atr_period", 10))
        self.m = float(self.p("multiplier", 3.0))
        self.mp = int(self.p("mom_period", 10))
        self.mt = float(self.p("mom_thresh", 0.0))
        self._trs = deque(maxlen=self.n)
        self._closes = deque(maxlen=self.mp + 1)
        self._prev_close = None
        self._prev_upper = self._prev_lower = None
        self._trend = 0        # 1 up, -1 down
        self._prev_trend = 0

    def _atr(self, bar: Bar) -> float | None:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(bar.high - bar.low,
                     abs(bar.high - self._prev_close),
                     abs(bar.low - self._prev_close))
        self._trs.append(tr)
        return sum(self._trs) / len(self._trs) if len(self._trs) == self.n else None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        atr = self._atr(bar)
        self._closes.append(bar.close)
        c = bar.close
        self._prev_close = c
        if atr is None:
            return Signal.HOLD

        hl2 = (bar.high + bar.low) / 2
        upper = hl2 + self.m * atr
        lower = hl2 - self.m * atr
        if self._prev_upper is not None:
            upper = min(upper, self._prev_upper) if c <= self._prev_upper else upper
            lower = max(lower, self._prev_lower) if c >= self._prev_lower else lower
        self._prev_upper, self._prev_lower = upper, lower

        self._prev_trend = self._trend
        if self._trend >= 0 and c < lower:
            self._trend = -1
        elif self._trend <= 0 and c > upper:
            self._trend = 1

        if len(self._closes) <= self.mp:
            return Signal.HOLD
        roc = (c / self._closes[0] - 1) * 100

        if self._prev_trend != 1 and self._trend == 1 and roc > self.mt:
            return Signal.BUY
        if self._prev_trend != -1 and self._trend == -1 and roc < -self.mt:
            return Signal.SELL
        return Signal.HOLD

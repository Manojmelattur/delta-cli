"""Supertrend + momentum (ROC) filter.

Params: atr_period(10), multiplier(3.0), mom_period(10), mom_thresh(0.0)
Enters long when Supertrend flips up AND ROC > threshold; short on opposite.
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class SupertrendMomentum(Strategy):
    name = "supertrend_mom"
    regime = "trend"

    def on_start(self):
        self.n = int(self.p("atr_period", 10))
        self.m = float(self.p("multiplier", 3.0))
        self.mp = int(self.p("mom_period", 10))
        self.mt = float(self.p("mom_thresh", 0.0))
        self._init_state()

    def _init_state(self):
        self._trs: deque[float] = deque(maxlen=self.n)
        self._closes: deque[float] = deque(maxlen=self.mp + 1)
        self._prev_close: float | None = None
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None
        self._trend = 0       # 1 = up, -1 = down, 0 = uninitialised
        self._prev_trend = 0
        self._state = 0       # 1 = long, -1 = short, 0 = flat

    def _atr(self, bar: Bar) -> float | None:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - self._prev_close),
                abs(bar.low - self._prev_close),
            )
        self._trs.append(tr)
        return sum(self._trs) / len(self._trs) if len(self._trs) == self.n else None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        # Capture previous close before any updates.
        prev_c = self._prev_close
        atr = self._atr(bar)
        c = bar.close
        self._closes.append(c)

        if atr is None:
            self._prev_close = c
            return Signal.HOLD

        hl2 = (bar.high + bar.low) / 2
        upper = hl2 + self.m * atr
        lower = hl2 - self.m * atr

        # Clamp bands using previous close.
        # Tighten upper only when prev close was above it (uptrend).
        # Raise lower only when prev close was below it (downtrend).
        if self._prev_upper is not None and self._prev_lower is not None and prev_c is not None:
            upper = min(upper, self._prev_upper) if prev_c >= self._prev_upper else upper
            lower = max(lower, self._prev_lower) if prev_c <= self._prev_lower else lower

        self._prev_upper = upper
        self._prev_lower = lower

        # Trend flip: use != to avoid treating uninitialised 0 as a trend direction.
        self._prev_trend = self._trend
        if self._trend != -1 and c < lower:
            self._trend = -1
        elif self._trend != 1 and c > upper:
            self._trend = 1

        self._prev_close = c

        if len(self._closes) <= self.mp:
            return Signal.HOLD

        roc = (c / self._closes[0] - 1) * 100

        if self._prev_trend != 1 and self._trend == 1 and roc > self.mt and self._state != 1:
            self._state = 1
            return Signal.BUY
        if self._prev_trend != -1 and self._trend == -1 and roc < -self.mt and self._state != -1:
            self._state = -1
            return Signal.SELL

        return Signal.HOLD

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

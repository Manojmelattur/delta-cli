"""Bollinger Bands strategy.

Params: period(20), stdev(2.0), mode("revert"|"breakout")
"""
from __future__ import annotations

from collections import deque
import math

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Bollinger(Strategy):
    name = "bollinger"

    regime = "range"
    def on_start(self):
        self.n = int(self.p("period", 20))
        self.k = float(self.p("stdev", 2.0))
        self.mode = self.p("mode", "revert")
        self.w = deque(maxlen=self.n)
        self._state = 0
        self._intent = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0
        self.w.append(bar.close)
        if len(self.w) < self.n:
            return Signal.HOLD
        mean = sum(self.w) / self.n
        var = sum((x - mean) ** 2 for x in self.w) / self.n
        sd = math.sqrt(var)
        upper = mean + self.k * sd; lower = mean - self.k * sd
        c = bar.close
        if self.mode == "revert":
            if c < lower:
                self._intent = 1
            elif c > upper:
                self._intent = -1
            elif self._intent == 1 and c >= mean:
                self._intent = 0
            elif self._intent == -1 and c <= mean:
                self._intent = 0
            if c < lower and self._state != 1: self._state = 1; return Signal.BUY
            if c > upper and self._state != -1: self._state = -1; return Signal.SELL
            if self._state == 1 and c >= mean: self._state = 0; return Signal.FLAT
            if self._state == -1 and c <= mean: self._state = 0; return Signal.FLAT
        else:
            if c > upper:
                self._intent = 1
            elif c < lower:
                self._intent = -1
            if c > upper and self._state != 1: self._state = 1; return Signal.BUY
            if c < lower and self._state != -1: self._state = -1; return Signal.SELL
        return Signal.HOLD

    def intent(self, bar: Bar):
        """Current desired position based on the last closed bar's price
        vs the bands. Used by the scheduler when the crossing itself is
        outside the tail window but the setup is still valid."""
        if len(self.w) < self.n:
            return None
        mean = sum(self.w) / self.n
        var = sum((x - mean) ** 2 for x in self.w) / self.n
        sd = math.sqrt(var)
        upper = mean + self.k * sd; lower = mean - self.k * sd
        c = bar.close
        if self.mode == "revert":
            # After an extreme-band touch, the mean-reversion setup remains
            # valid until price reaches the middle band. Scheduler warmup
            # replays flat, so this stateful intent prevents 1h+ blackouts
            # when the touch happened a few bars before the tick.
            if self._intent == 1 and c >= mean: return Signal.FLAT
            if self._intent == -1 and c <= mean: return Signal.FLAT
            if self._state == 1 and c >= mean: return Signal.FLAT
            if self._state == -1 and c <= mean: return Signal.FLAT
            
            if self._intent == 1 and c < mean: return Signal.BUY
            if self._intent == -1 and c > mean: return Signal.SELL
            if self._state == 1 and c < mean: return Signal.BUY
            if self._state == -1 and c > mean: return Signal.SELL
            if c < lower: return Signal.BUY
            if c > upper: return Signal.SELL
        else:
            if self._intent == 1: return Signal.BUY
            if self._intent == -1: return Signal.SELL
            if self._state == 1: return Signal.BUY
            if self._state == -1: return Signal.SELL
            if c > upper: return Signal.BUY
            if c < lower: return Signal.SELL
        return None

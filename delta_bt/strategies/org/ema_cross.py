"""Example strategy: EMA crossover.

Params:
    fast (int, default 9)
    slow (int, default 21)
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class EmaCross(Strategy):
    name = "ema_cross"

    regime = "trend"
    def on_start(self):
        self.fast = int(self.p("fast", 9))
        self.slow = int(self.p("slow", 21))
        self.ema_f: float | None = None
        self.ema_s: float | None = None
        self.k_f = 2 / (self.fast + 1)
        self.k_s = 2 / (self.slow + 1)
        self._prev_diff: float | None = None
        self._warm = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        px = bar.close
        self.ema_f = px if self.ema_f is None else (px - self.ema_f) * self.k_f + self.ema_f
        self.ema_s = px if self.ema_s is None else (px - self.ema_s) * self.k_s + self.ema_s
        self._warm += 1
        if self._warm < self.slow:
            return Signal.HOLD
        diff = self.ema_f - self.ema_s
        sig = Signal.HOLD
        if self._prev_diff is not None:
            if self._prev_diff <= 0 < diff:
                sig = Signal.BUY
            elif self._prev_diff >= 0 > diff:
                sig = Signal.SELL
        self._prev_diff = diff
        return sig

    def intent(self, bar: Bar):
        if self.ema_f is None or self.ema_s is None:
            return None
        diff = self.ema_f - self.ema_s
        if diff > 0:
            return Signal.BUY
        elif diff < 0:
            return Signal.SELL
        return None

"""Triple EMA trend strategy.

Params: fast(9), mid(21), slow(55). Long when fast>mid>slow, short when reverse.
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class ThreeEma(Strategy):
    name = "ema3"

    regime = "trend"
    def on_start(self):
        self.f = int(self.p("fast", 9))
        self.m = int(self.p("mid", 21))
        self.s = int(self.p("slow", 55))
        self.ef = self.em = self.es = None
        self.kf = 2 / (self.f + 1); self.km = 2 / (self.m + 1); self.ks = 2 / (self.s + 1)
        self._warm = 0
        self._state = 0  # 1 long, -1 short

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        c = bar.close
        self.ef = c if self.ef is None else (c - self.ef) * self.kf + self.ef
        self.em = c if self.em is None else (c - self.em) * self.km + self.em
        self.es = c if self.es is None else (c - self.es) * self.ks + self.es
        self._warm += 1
        if self._warm < self.s:
            return Signal.HOLD
        if self.ef > self.em > self.es and self._state != 1:
            self._state = 1; return Signal.BUY
        if self.ef < self.em < self.es and self._state != -1:
            self._state = -1; return Signal.SELL
        return Signal.HOLD

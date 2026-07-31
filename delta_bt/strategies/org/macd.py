"""MACD crossover — another popular baseline.

Params: fast(12), slow(26), signal(9).
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Macd(Strategy):
    name = "macd"

    regime = "trend"
    def on_start(self):
        self.f = int(self.p("fast", 12)); self.s = int(self.p("slow", 26))
        self.sg = int(self.p("signal", 9))
        self.ef = self.es = self.esig = None
        self.kf = 2 / (self.f + 1); self.ks = 2 / (self.s + 1); self.ksg = 2 / (self.sg + 1)
        self._prev_hist = None
        self._warm = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        c = bar.close
        self.ef = c if self.ef is None else (c - self.ef) * self.kf + self.ef
        self.es = c if self.es is None else (c - self.es) * self.ks + self.es
        macd = self.ef - self.es
        self.esig = macd if self.esig is None else (macd - self.esig) * self.ksg + self.esig
        hist = macd - self.esig
        self._warm += 1
        if self._warm < self.s + self.sg:
            self._prev_hist = hist; return Signal.HOLD
        sig = Signal.HOLD
        if self._prev_hist is not None:
            if self._prev_hist <= 0 < hist: sig = Signal.BUY
            elif self._prev_hist >= 0 > hist: sig = Signal.SELL
        self._prev_hist = hist
        return sig

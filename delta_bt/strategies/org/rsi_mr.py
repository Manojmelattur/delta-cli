"""Example strategy: RSI mean-reversion.

Params: period (14), oversold (30), overbought (70).
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class RsiMeanRev(Strategy):
    name = "rsi_mr"

    regime = "range"
    def on_start(self):
        self.period = int(self.p("period", 14))
        self.os = float(self.p("oversold", 30))
        self.ob = float(self.p("overbought", 70))
        self._prev: float | None = None
        self._gains = deque(maxlen=self.period)
        self._losses = deque(maxlen=self.period)
        self._rsi: float | None = None
        self._intent_state = 0

    def _compute_rsi(self) -> float | None:
        if len(self._gains) < self.period:
            return None
        ag = sum(self._gains) / self.period
        al = sum(self._losses) / self.period or 1e-9
        return 100 - 100 / (1 + ag / al)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        px = bar.close
        if self._prev is None:
            self._prev = px
            return Signal.HOLD
        chg = px - self._prev
        self._prev = px
        self._gains.append(max(chg, 0))
        self._losses.append(max(-chg, 0))
        rsi = self._compute_rsi()
        if rsi is None:
            return Signal.HOLD
        self._rsi = rsi
        if rsi <= self.os:
            self._intent_state = 1
        elif rsi >= self.ob:
            self._intent_state = -1
        elif self._intent_state == 1 and rsi >= 50:
            self._intent_state = 0
        elif self._intent_state == -1 and rsi <= 50:
            self._intent_state = 0
        if rsi < self.os:
            return Signal.BUY
        if rsi > self.ob:
            return Signal.SELL
        return Signal.HOLD

    def intent(self, bar: Bar):
        if self._rsi is None:
            return None
        if self._intent_state == 1: return Signal.BUY
        if self._intent_state == -1: return Signal.SELL
        if self._rsi <= self.os: return Signal.BUY
        if self._rsi >= self.ob: return Signal.SELL
        return None

"""Example strategy: RSI mean-reversion.

Params: period (14), oversold (30), overbought (70).
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class RsiMeanRev(Strategy):
    name = "rsi_mr"
    regime = "range"

    def on_start(self):
        self.period = int(self.p("period", 14))
        self.os = float(self.p("oversold", 30))
        self.ob = float(self.p("overbought", 70))
        self._init_state()

    def _init_state(self):
        self._prev: float | None = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._warm = 0
        self._rsi: float | None = None
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _update_rsi(self, px: float):
        if self._prev is None:
            self._prev = px
            return
        chg = px - self._prev
        self._prev = px
        gain = max(chg, 0.0)
        loss = max(-chg, 0.0)
        self._warm += 1
        if self._warm <= self.period:
            # Seed phase: accumulate simple average over first `period` bars.
            self._avg_gain += gain / self.period
            self._avg_loss += loss / self.period
        else:
            # Wilder's smoothing.
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
        if self._warm < self.period:
            return
        al = self._avg_loss if self._avg_loss > 0 else 1e-9
        self._rsi = 100 - 100 / (1 + self._avg_gain / al)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._update_rsi(bar.close)
        if self._rsi is None:
            return Signal.HOLD

        # Gate signals: only fire on the first bar the threshold is crossed.
        if self._rsi < self.os and self._state != 1:
            self._state = 1
            return Signal.BUY
        if self._rsi > self.ob and self._state != -1:
            self._state = -1
            return Signal.SELL

        return Signal.HOLD

    def intent(self) -> Signal:
        if self._rsi is None:
            return Signal.HOLD
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        if self._rsi <= self.os:
            return Signal.BUY
        if self._rsi >= self.ob:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

"""Example strategy: Momentum Breakout.

Triggered by sudden explosive moves in volume and price.

Params:
    lookback  (int,   default 10)  — Rolling window for high/low and average volume
    vol_mult  (float, default 1.5) — Volume must exceed lookback average by this factor
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class MomentumBreakout(Strategy):
    name = "momentum_breakout"
    regime = "trend"

    def on_start(self):
        self.lookback = int(self.p("lookback", 10))
        self.vol_mult = float(self.p("vol_mult", 1.5))
        self._init_state()

    def _init_state(self):
        self._bars: deque[Bar] = deque(maxlen=self.lookback)
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._bars.append(bar)

        if len(self._bars) < self.lookback:
            return Signal.HOLD

        # Exclude the current bar when computing the prior window.
        prior = list(self._bars)[:-1]
        recent_high = max(b.high for b in prior)
        recent_low = min(b.low for b in prior)

        # Volume confirmation: current bar volume must exceed the prior average.
        avg_vol = sum(b.volume for b in prior) / len(prior)
        volume_confirmed = bar.volume > avg_vol * self.vol_mult

        if bar.close > recent_high and volume_confirmed and self._state != 1:
            self._state = 1
            return Signal.BUY
        elif bar.close < recent_low and volume_confirmed and self._state != -1:
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

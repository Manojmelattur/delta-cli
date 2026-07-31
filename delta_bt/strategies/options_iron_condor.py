"""
Automated 0DTE Options Iron Condor Strategy.

Sells OTM Call & Put Credit Spreads on daily expiry options when the
underlying is in a low-volatility range (inside Bollinger Bands).
Signals SELL (enter condor credit) when range-bound, HOLD otherwise.

Params:
    bb_period    (int,   default 20)   — Bollinger Band lookback
    bb_std       (float, default 2.0)  — Bollinger Band std multiplier
    delta_target (float, default 0.15) — Target delta for short strikes
"""
from __future__ import annotations

import math
from collections import deque

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext


class OptionsIronCondorStrategy(Strategy):
    name = "options_iron_condor"
    regime = "range"

    def on_start(self):
        self.bb_period = int(self.p("bb_period", 20))
        self.bb_std = float(self.p("bb_std", 2.0))
        self.delta_target = float(self.p("delta_target", 0.15))
        self._init_state()

    def _init_state(self):
        self._bars: deque[Bar] = deque(maxlen=self.bb_period)
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _bollinger_bands(self) -> tuple[float, float]:
        """Return (lower_band, upper_band) over the current window."""
        closes = [b.close for b in self._bars]
        sma = sum(closes) / self.bb_period
        variance = sum((x - sma) ** 2 for x in closes) / self.bb_period
        std_dev = math.sqrt(variance)
        return sma - self.bb_std * std_dev, sma + self.bb_std * std_dev

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._bars.append(bar)

        if len(self._bars) < self.bb_period:
            return Signal.HOLD

        lower_band, upper_band = self._bollinger_bands()

        # Range-bound: sell Iron Condor when price comfortably inside bands
        # and not already in a short position.
        if lower_band < bar.close < upper_band and self._state != -1:
            self._state = -1
            return Signal.SELL  # short-vol credit position

        return Signal.HOLD

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

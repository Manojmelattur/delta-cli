"""Example strategy: Grid Trading (Basic Mean Reversion).

Params:
    grid_size (int, default 10): Number of bars for the range
    deviation (float, default 0.5): Percent deviation to trigger reverse trades
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Grid(Strategy):
    name = "grid"
    regime = "mean_reversion"

    def on_start(self):
        self.grid_size = int(self.p("grid_size", 10))
        self.deviation = float(self.p("deviation", 0.5)) / 100.0
        self._init_state()

    def _init_state(self):
        self.history: deque[float] = deque(maxlen=self.grid_size)
        self._warm = 0
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self.history.append(bar.close)

        # Wait for a full window before producing signals.
        self._warm += 1
        if self._warm <= self.grid_size:
            return Signal.HOLD

        recent_max = max(self.history)
        recent_min = min(self.history)
        mid = (recent_max + recent_min) / 2

        # If price drops below mid by deviation %, BUY (only if not already long).
        if bar.close < mid * (1 - self.deviation) and self._state != 1:
            self._state = 1
            return Signal.BUY
        # If price rises above mid by deviation %, SELL (only if not already short).
        elif bar.close > mid * (1 + self.deviation) and self._state != -1:
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

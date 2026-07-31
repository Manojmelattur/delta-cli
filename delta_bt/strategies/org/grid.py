"""Example strategy: Grid Trading (Basic Mean Reversion).

Params:
    grid_size (int, default 10): Number of bars for the range
    deviation (float, default 0.5): Percent deviation to trigger reverse trades
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal

class Grid(Strategy):
    name = "grid"
    regime = "mean_reversion"
    
    def on_start(self):
        self.grid_size = int(self.p("grid_size", 10))
        self.deviation = float(self.p("deviation", 0.5)) / 100.0
        self.history = []
        self._warm = 0
        
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self.history.append(bar.close)
        if len(self.history) > self.grid_size:
            self.history.pop(0)
            
        self._warm += 1
        if self._warm < self.grid_size:
            return Signal.HOLD
            
        # Basic channel logic for grid
        recent_max = max(self.history)
        recent_min = min(self.history)
        mid = (recent_max + recent_min) / 2
        
        # If price drops below the mid point by deviation %, BUY
        if bar.close < mid * (1 - self.deviation):
            return Signal.BUY
        # If price rises above the mid point by deviation %, SELL
        elif bar.close > mid * (1 + self.deviation):
            return Signal.SELL
            
        return Signal.HOLD

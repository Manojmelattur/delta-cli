"""Example strategy: Momentum Breakout.

Triggered by sudden explosive moves in volume and price.
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal

class MomentumBreakout(Strategy):
    name = "momentum_breakout"
    regime = "trend"
    
    def on_start(self):
        self.lookback = int(self.p("lookback", 10))
        self.history = []
        
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self.history.append(bar)
        if len(self.history) > self.lookback:
            self.history.pop(0)
            
        if len(self.history) < self.lookback:
            return Signal.HOLD
            
        recent_high = max(b.high for b in self.history[:-1])
        recent_low = min(b.low for b in self.history[:-1])
        
        # Breakout
        if bar.close > recent_high:
            return Signal.BUY
        elif bar.close < recent_low:
            return Signal.SELL
            
        return Signal.HOLD

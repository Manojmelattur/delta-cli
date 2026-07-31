"""VWAP Standard Deviation Bands Strategy.

Combines daily VWAP with rolling standard deviation bands and an RSI filter.
Buy when price hits lower band (oversold), Sell when price hits upper band (overbought).

Params:
- mult (float): standard deviation multiplier (default 2.0)
- stdev_len (int): rolling window for standard deviation (default 50)
- rsi_len (int): RSI length (default 14)
- rsi_buy_max (float): Max RSI to allow buys (default 40)
- rsi_sell_min (float): Min RSI to allow sells (default 60)
"""
from __future__ import annotations

import math
from collections import deque
from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal

class VwapBands(Strategy):
    name = "vwap_bands"
    regime = "ranging"

    def on_start(self):
        self.mult = float(self.p("mult", 2.0))
        self.stdev_len = int(self.p("stdev_len", 50))
        self.rsi_len = int(self.p("rsi_len", 14))
        self.rsi_buy_max = float(self.p("rsi_buy_max", 45.0))
        self.rsi_sell_min = float(self.p("rsi_sell_min", 55.0))
        
        self._day = None
        self._pv = 0.0
        self._v = 0.0
        
        self._closes = deque(maxlen=self.stdev_len)
        
        # RSI state
        self._gains = deque(maxlen=self.rsi_len)
        self._losses = deque(maxlen=self.rsi_len)
        self._prev_close = None
        
        self._state = 0
        self._prev_upper = None
        self._prev_lower = None

    def _calc_rsi(self) -> float:
        if len(self._gains) < self.rsi_len:
            return 50.0
        avg_gain = sum(self._gains) / self.rsi_len
        avg_loss = sum(self._losses) / self.rsi_len
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        d = bar.ts.date()
        if d != self._day:
            self._day = d
            self._pv = 0.0
            self._v = 0.0
            
        typical = (bar.high + bar.low + bar.close) / 3.0
        vol = bar.volume if bar.volume > 0 else 1.0
        self._pv += typical * vol
        self._v += vol
        
        vwap = self._pv / self._v if self._v > 0 else bar.close
        
        self._closes.append(bar.close)
        
        # Update RSI
        if self._prev_close is not None:
            change = bar.close - self._prev_close
            self._gains.append(change if change > 0 else 0)
            self._losses.append(-change if change < 0 else 0)
        
        pc = self._prev_close
        self._prev_close = bar.close

        # Reset latch if flat
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        if len(self._closes) < self.stdev_len or pc is None:
            return Signal.HOLD
            
        # Calculate std dev
        mean = sum(self._closes) / len(self._closes)
        variance = sum((x - mean) ** 2 for x in self._closes) / len(self._closes)
        std = math.sqrt(variance)
        
        upper = vwap + (self.mult * std)
        lower = vwap - (self.mult * std)
        
        pu = self._prev_upper
        pl = self._prev_lower
        self._prev_upper = upper
        self._prev_lower = lower
        
        if pu is None or pl is None:
            return Signal.HOLD
            
        rsi = self._calc_rsi()
        c = bar.close
        
        # Edge triggers for mean reversion: 
        # Buy when price crosses BELOW lower band (oversold), and RSI is low.
        crossed_down_lower = pc >= pl and c < lower
        # Sell when price crosses ABOVE upper band (overbought), and RSI is high.
        crossed_up_upper = pc <= pu and c > upper
        
        if crossed_down_lower and rsi <= self.rsi_buy_max and self._state != 1:
            self._state = 1
            return Signal.BUY
            
        if crossed_up_upper and rsi >= self.rsi_sell_min and self._state != -1:
            self._state = -1
            return Signal.SELL
            
        return Signal.HOLD

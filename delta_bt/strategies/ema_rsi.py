"""EMA + RSI Trend-Following / Pullback Strategy.

Buy when price is above EMA (uptrend) and RSI drops below oversold (pullback).
Sell when price is below EMA (downtrend) and RSI spikes above overbought (pullback).
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class EmaRsi(Strategy):
    name = "ema_rsi"
    regime = "trend"  # Tends to work well as a trend-pullback strategy

    def on_start(self):
        self.ema_period = int(self.p("ema_period", 50))
        self.rsi_period = int(self.p("rsi_period", 14))
        self.os = float(self.p("oversold", 30))
        self.ob = float(self.p("overbought", 70))
        self._init_state()

    def _init_state(self):
        self._ema: float | None = None
        self._ema_warm = 0
        self._ema_sum = 0.0
        self._ema_k = 2.0 / (self.ema_period + 1.0)
        
        self._prev: float | None = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._warm = 0
        self._rsi: float | None = None
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _update_indicators(self, px: float):
        # Update EMA
        if self._ema is None:
            self._ema_warm += 1
            self._ema_sum += px
            if self._ema_warm == self.ema_period:
                self._ema = self._ema_sum / self.ema_period
        else:
            self._ema = (px - self._ema) * self._ema_k + self._ema

        # Update RSI
        if self._prev is None:
            self._prev = px
            return
        chg = px - self._prev
        self._prev = px
        gain = max(chg, 0.0)
        loss = max(-chg, 0.0)
        self._warm += 1
        if self._warm <= self.rsi_period:
            self._avg_gain += gain / self.rsi_period
            self._avg_loss += loss / self.rsi_period
        else:
            self._avg_gain = (self._avg_gain * (self.rsi_period - 1) + gain) / self.rsi_period
            self._avg_loss = (self._avg_loss * (self.rsi_period - 1) + loss) / self.rsi_period
            
        if self._warm >= self.rsi_period:
            al = self._avg_loss if self._avg_loss > 0 else 1e-9
            self._rsi = 100 - 100 / (1 + self._avg_gain / al)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after SL/TP works
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._update_indicators(bar.close)

        if self._ema is None or self._rsi is None:
            return Signal.HOLD

        # Trend filter (EMA) and Pullback condition (RSI)
        is_uptrend = bar.close > self._ema
        is_downtrend = bar.close < self._ema

        if is_uptrend and self._rsi < self.os and self._state != 1:
            self._state = 1
            return Signal.BUY
        
        if is_downtrend and self._rsi > self.ob and self._state != -1:
            self._state = -1
            return Signal.SELL

        return Signal.HOLD

    def intent(self) -> Signal:
        if self._ema is None or self._rsi is None:
            return Signal.HOLD
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
            
        is_uptrend = self._prev and self._ema and self._prev > self._ema
        is_downtrend = self._prev and self._ema and self._prev < self._ema
        
        if is_uptrend and self._rsi <= self.os:
            return Signal.BUY
        if is_downtrend and self._rsi >= self.ob:
            return Signal.SELL
            
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

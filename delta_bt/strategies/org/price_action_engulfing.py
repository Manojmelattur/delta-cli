"""Price-action Engulfing candle strategy (trend-aligned).

Enters on a bullish/bearish engulfing candle whose direction matches the
higher-EMA trend and whose close is near the far side of its range.

Params:
  ema_len (int, 50)         trend filter EMA length
  min_body_ratio (float, 1.2) engulfing body vs prior body
  close_frac (float, 0.6)   close must be in top/bottom `close_frac` of range
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Engulfing(Strategy):
    name = "price_action_engulfing"

    regime = "any"
    def on_start(self):
        self.ema_len = int(self.p("ema_len", 50))
        self.min_body_ratio = float(self.p("min_body_ratio", 1.2))
        self.close_frac = float(self.p("close_frac", 0.6))
        self.ema = None
        self.k = 2 / (self.ema_len + 1)
        self.prev: Bar | None = None
        self._state = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0
        self.ema = bar.close if self.ema is None else \
            (bar.close - self.ema) * self.k + self.ema
        prev = self.prev
        self.prev = bar
        if prev is None:
            return Signal.HOLD

        rng = max(bar.high - bar.low, 1e-9)
        body = abs(bar.close - bar.open)
        prev_body = max(abs(prev.close - prev.open), 1e-9)
        body_ok = body >= self.min_body_ratio * prev_body

        bull_eng = (prev.close < prev.open
                    and bar.close > bar.open
                    and bar.close >= prev.open
                    and bar.open <= prev.close
                    and body_ok
                    and (bar.close - bar.low) / rng >= self.close_frac)
        bear_eng = (prev.close > prev.open
                    and bar.close < bar.open
                    and bar.close <= prev.open
                    and bar.open >= prev.close
                    and body_ok
                    and (bar.high - bar.close) / rng >= self.close_frac)

        if bull_eng and bar.close > self.ema and self._state != 1:
            self._state = 1; return Signal.BUY
        if bear_eng and bar.close < self.ema and self._state != -1:
            self._state = -1; return Signal.SELL
        return Signal.HOLD

"""SMC Liquidity Sweep strategy.

Detects a sweep of a prior swing high/low (stop-hunt) followed by a rejection
close back inside the range. This is the classic "grab liquidity then reverse"
pattern used by SMC traders.

Logic:
- Track the highest high and lowest low of the last `lookback` bars.
- Bullish sweep: current bar's low pierces prior swing low but close is back
  above it AND close > open (rejection wick).
- Bearish sweep: current bar's high pierces prior swing high but close is
  back below it AND close < open.

Params:
  lookback (int, default 20)   number of bars used to define swing levels
  wick_ratio (float, 0.5)      min lower/upper wick fraction of range
  cooldown (int, 3)            bars to wait between signals
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class SmcLiquiditySweep(Strategy):
    name = "smc_liquidity_sweep"

    regime = "range"
    def on_start(self):
        self.lookback = int(self.p("lookback", 20))
        self.wick_ratio = float(self.p("wick_ratio", 0.5))
        self.cooldown = int(self.p("cooldown", 3))
        self.buf: deque[Bar] = deque(maxlen=self.lookback + 1)
        self._state = 0
        self._cd = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0
        self.buf.append(bar)
        if self._cd > 0:
            self._cd -= 1
        if len(self.buf) < self.lookback + 1:
            return Signal.HOLD

        prior = list(self.buf)[:-1]
        swing_hi = max(b.high for b in prior)
        swing_lo = min(b.low for b in prior)
        rng = max(bar.high - bar.low, 1e-9)
        upper_wick = bar.high - max(bar.close, bar.open)
        lower_wick = min(bar.close, bar.open) - bar.low

        if self._cd == 0:
            # bullish sweep of swing low
            if (bar.low < swing_lo and bar.close > swing_lo
                    and bar.close > bar.open
                    and (lower_wick / rng) >= self.wick_ratio
                    and self._state != 1):
                self._state = 1
                self._cd = self.cooldown
                return Signal.BUY
            # bearish sweep of swing high
            if (bar.high > swing_hi and bar.close < swing_hi
                    and bar.close < bar.open
                    and (upper_wick / rng) >= self.wick_ratio
                    and self._state != -1):
                self._state = -1
                self._cd = self.cooldown
                return Signal.SELL
        return Signal.HOLD

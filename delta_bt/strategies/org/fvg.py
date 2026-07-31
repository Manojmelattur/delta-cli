"""Fair Value Gap (FVG) strategy.

Detects 3-bar FVGs on the most recent closed candles:
- Bullish FVG: low[0] > high[2]  (gap between bar-2 high and bar-0 low)
- Bearish FVG: high[0] < low[2]

Enters in the direction of the last FVG when price retests the gap.
Params: lookback_close(50) — how long a gap stays valid.
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Fvg(Strategy):
    name = "fvg"

    regime = "any"
    def on_start(self):
        self.lookback = int(self.p("lookback_close", 50))
        self.bars: deque[Bar] = deque(maxlen=3)
        self.gaps: list = []   # (side, lo, hi, age)
        self._state = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0
        self.bars.append(bar)
        # detect new gap using closed 3-bar window
        if len(self.bars) == 3:
            b2, b1, b0 = self.bars[0], self.bars[1], self.bars[2]
            if b0.low > b2.high:
                self.gaps.append(["BUY", b2.high, b0.low, 0])
            elif b0.high < b2.low:
                self.gaps.append(["SELL", b0.high, b2.low, 0])

        # check retests
        for g in list(self.gaps):
            side, lo, hi, age = g
            g[3] += 1
            if g[3] > self.lookback:
                self.gaps.remove(g); continue
            if lo <= bar.close <= hi:
                self.gaps.remove(g)
                if side == "BUY" and self._state != 1:
                    self._state = 1; return Signal.BUY
                if side == "SELL" and self._state != -1:
                    self._state = -1; return Signal.SELL
        return Signal.HOLD

"""SMC CHoCH / BOS strategy.

Tracks swing highs/lows over `swing` bars.
- BOS (Break Of Structure): trend continues — new HH in uptrend / new LL in downtrend.
- CHoCH (Change of Character): trend flip — LH after uptrend HHs, or HL after downtrend LLs.

Signal: BUY on bullish CHoCH or bullish BOS; SELL on bearish CHoCH / BOS.

Params: swing(5) — half-window for swing pivots.
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class SmcChoChBos(Strategy):
    name = "smc_choch_bos"

    regime = "trend"
    def on_start(self):
        self.w = int(self.p("swing", 5))
        self.buf: deque[Bar] = deque(maxlen=self.w * 2 + 1)
        self.last_high = None
        self.last_low = None
        self.trend = 0
        self._state = 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0
        self.buf.append(bar)
        if len(self.buf) < self.buf.maxlen:
            return Signal.HOLD
        mid = self.buf[self.w]
        highs = [b.high for b in self.buf]
        lows = [b.low for b in self.buf]
        is_swing_high = mid.high == max(highs)
        is_swing_low = mid.low == min(lows)

        sig = Signal.HOLD
        if is_swing_high:
            if self.last_high is not None:
                if mid.high > self.last_high:
                    if self.trend == 1:  # BOS up
                        if self._state != 1: self._state = 1; sig = Signal.BUY
                    else:                 # CHoCH bullish
                        self.trend = 1
                        if self._state != 1: self._state = 1; sig = Signal.BUY
                else:
                    if self.trend == 1:  # LH — CHoCH bearish setup
                        self.trend = -1
                        if self._state != -1: self._state = -1; sig = Signal.SELL
            self.last_high = mid.high

        if is_swing_low:
            if self.last_low is not None:
                if mid.low < self.last_low:
                    if self.trend == -1:  # BOS down
                        if self._state != -1: self._state = -1; sig = Signal.SELL
                    else:
                        self.trend = -1
                        if self._state != -1: self._state = -1; sig = Signal.SELL
                else:
                    if self.trend == -1:  # HL — CHoCH bullish setup
                        self.trend = 1
                        if self._state != 1: self._state = 1; sig = Signal.BUY
            self.last_low = mid.low

        return sig

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
        self._init_state()

    def _init_state(self):
        self.buf: deque[Bar] = deque(maxlen=self.w * 2 + 1)
        self.last_high: float | None = None
        self.last_low: float | None = None
        self.trend = 0
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self.buf.append(bar)
        if len(self.buf) < self.w * 2 + 1:
            return Signal.HOLD

        mid = self.buf[self.w]
        highs = [b.high for b in self.buf]
        lows = [b.low for b in self.buf]
        is_swing_high = mid.high == max(highs)
        is_swing_low = mid.low == min(lows)

        sig = Signal.HOLD

        if is_swing_high:
            last_high = self.last_high
            if last_high is not None:
                if mid.high > last_high:
                    if self.trend == 1:  # BOS up
                        if self._state != 1:
                            self._state = 1
                            sig = Signal.BUY
                    else:               # CHoCH bullish
                        self.trend = 1
                        if self._state != 1:
                            self._state = 1
                            sig = Signal.BUY
                else:
                    if self.trend == 1:  # LH — CHoCH bearish
                        self.trend = -1
                        if self._state != -1:
                            self._state = -1
                            sig = Signal.SELL
            self.last_high = mid.high

        if is_swing_low:
            last_low = self.last_low
            if last_low is not None:
                if mid.low < last_low:
                    if self.trend == -1:  # BOS down
                        if self._state != -1:
                            self._state = -1
                            sig = Signal.SELL
                    else:               # CHoCH bearish
                        self.trend = -1
                        if self._state != -1:
                            self._state = -1
                            sig = Signal.SELL
                else:
                    if self.trend == -1:  # HL — CHoCH bullish
                        self.trend = 1
                        if self._state != 1:
                            self._state = 1
                            sig = Signal.BUY
            self.last_low = mid.low

        return sig

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

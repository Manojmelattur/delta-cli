"""SMC Break-of-Structure + Retest strategy.

Higher win-rate variant of raw BOS: waits for the breakout candle, then only
enters when price *retests* the broken level from the correct side.

Logic:
- Track swing high/low over `swing` bars (pivot on middle bar).
- On close beyond a swing (BOS), remember the broken level and direction.
- Fire BUY/SELL when a subsequent bar wicks back into the broken level and
  closes in the breakout direction, within `retest_window` bars.

Params:
  swing (int, 5)          half-window for swing detection
  retest_window (int, 15) max bars to wait for a retest
  buffer_pct (float, 0.1) tolerance around the broken level
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class SmcBosRetest(Strategy):
    name = "smc_bos_retest"
    regime = "trend"

    def on_start(self):
        self.w = int(self.p("swing", 5))
        self.window = int(self.p("retest_window", 30))
        self.buf_pct = float(self.p("buffer_pct", 0.25))
        self._init_state()

    def _init_state(self):
        self.buf: deque[Bar] = deque(maxlen=self.w * 2 + 1)
        self.last_hi: float | None = None
        self.last_lo: float | None = None
        self.pending: list = []  # [direction(+1/-1), level, age]
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self.buf.append(bar)

        # Update pivots.
        if len(self.buf) == self.buf.maxlen:
            mid = self.buf[self.w]
            highs = [b.high for b in self.buf]
            lows = [b.low for b in self.buf]
            if mid.high == max(highs):
                self.last_hi = mid.high
            if mid.low == min(lows):
                self.last_lo = mid.low

        # Detect BOS on current bar.
        if self.last_hi is not None and bar.close > self.last_hi:
            self.pending.append([+1, self.last_hi, 0])
            self.last_hi = None
        if self.last_lo is not None and bar.close < self.last_lo:
            self.pending.append([-1, self.last_lo, 0])
            self.last_lo = None

        # Age and check retest — rebuild to avoid remove() hazard.
        buf = bar.close * (self.buf_pct / 100)
        signal = Signal.HOLD
        next_pending = []
        for p in self.pending:
            direction, level, _ = p
            p[2] += 1
            if p[2] > self.window:
                continue  # expired — drop
            if p[2] < 1:
                next_pending.append(p)
                continue  # don't retest the BOS bar itself
            fired = False
            if direction == +1:
                if bar.low <= level + buf and bar.close > level and self._state != 1:
                    self._state = 1
                    signal = Signal.BUY
                    fired = True
            else:
                if bar.high >= level - buf and bar.close < level and self._state != -1:
                    self._state = -1
                    signal = Signal.SELL
                    fired = True
            if not fired:
                next_pending.append(p)
        self.pending = next_pending
        return signal

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

"""ATR Channel Breakout strategy.

Builds a dynamic channel around a rolling midpoint using ATR as the
width. Enters on a breakout beyond the channel and exits when price
crosses back through the midpoint.

Params:
    mid_len     (int,   default 20)  — Rolling midpoint period (simple average of hl2)
    atr_len     (int,   default 14)  — ATR period
    atr_mult    (float, default 2.0) — Channel width multiplier
    atr_expand  (bool,  default True) — Only enter when ATR is expanding
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class AtrChannelBreakout(Strategy):
    name = "atr_channel_breakout"
    regime = "trend"

    def on_start(self):
        self.mid_len = int(self.p("mid_len", 20))
        self.atr_len = int(self.p("atr_len", 14))
        self.atr_mult = float(self.p("atr_mult", 2.0))
        self.atr_expand = bool(self.p("atr_expand", True))
        self._init_state()

    def _init_state(self):
        self._hl2_buf: deque[float] = deque(maxlen=self.mid_len)
        self._atr_buf: deque[float] = deque(maxlen=self.atr_len)
        self._prev_close: float | None = None
        self._prev_atr: float | None = None
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _calc_atr(self, bar: Bar) -> float:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - self._prev_close),
                abs(bar.low - self._prev_close),
            )
        self._atr_buf.append(tr)
        return sum(self._atr_buf) / len(self._atr_buf)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        atr = self._calc_atr(bar)
        self._prev_close = bar.close

        self._hl2_buf.append((bar.high + bar.low) / 2.0)

        # Wait for full windows.
        if (
            len(self._hl2_buf) < self.mid_len
            or len(self._atr_buf) < self.atr_len
        ):
            self._prev_atr = atr
            return Signal.HOLD

        mid = sum(self._hl2_buf) / self.mid_len
        upper = mid + self.atr_mult * atr
        lower = mid - self.atr_mult * atr

        prev_upper = self._prev_upper
        prev_lower = self._prev_lower
        prev_atr = self._prev_atr
        self._prev_upper = upper
        self._prev_lower = lower
        self._prev_atr = atr

        if prev_upper is None or prev_lower is None:
            return Signal.HOLD

        # ATR expansion filter: current ATR must exceed previous ATR.
        atr_expanding = (not self.atr_expand) or (prev_atr is not None and atr > prev_atr)

        c = bar.close
        in_long = self._state == 1
        in_short = self._state == -1

        # --- Exits: price crosses back through midpoint ---
        if in_long and c < mid:
            self._state = 0
            return Signal.FLAT
        if in_short and c > mid:
            self._state = 0
            return Signal.FLAT

        # --- Entries: fresh channel breakout with edge trigger ---
        crossed_up = c > upper and bar.open <= prev_upper
        crossed_down = c < lower and bar.open >= prev_lower

        if crossed_up and atr_expanding and self._state != 1:
            self._state = 1
            return Signal.BUY
        if crossed_down and atr_expanding and self._state != -1:
            self._state = -1
            return Signal.SELL

        return Signal.HOLD

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

"""Donchian Channel Breakout strategy.

Classic turtle-trading breakout: enters on a new N-bar high/low,
exits when price crosses the opposite mid-channel line.

Params:
    enter_len   (int, default 20)  — Breakout channel period
    exit_len    (int, default 10)  — Exit channel period (typically half of enter_len)
    atr_len     (int, default 14)  — ATR period for volatility filter
    atr_filter  (bool, default True) — Only enter when ATR is expanding
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class DonchianBreakout(Strategy):
    name = "donchian_breakout"
    regime = "trend"

    def on_start(self):
        self.enter_len = int(self.p("enter_len", 20))
        self.exit_len = int(self.p("exit_len", 10))
        self.atr_len = int(self.p("atr_len", 14))
        self.atr_filter = bool(self.p("atr_filter", True))
        self._init_state()

    def _init_state(self):
        # +1 to exclude the current bar from the channel calculation
        self._enter_buf: deque[Bar] = deque(maxlen=self.enter_len + 1)
        self._exit_buf: deque[Bar] = deque(maxlen=self.exit_len + 1)
        self._atr_buf: deque[float] = deque(maxlen=self.atr_len)
        self._prev_close: float | None = None
        self._avg_atr: float | None = None
        self._prev_atr: float | None = None
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

        self._enter_buf.append(bar)
        self._exit_buf.append(bar)

        # Wait for full windows.
        if (
            len(self._enter_buf) < self.enter_len + 1
            or len(self._exit_buf) < self.exit_len + 1
            or len(self._atr_buf) < self.atr_len
        ):
            self._prev_atr = atr
            return Signal.HOLD

        # Exclude current bar from channel calculation (prior bars only).
        enter_prior = list(self._enter_buf)[:-1]
        exit_prior = list(self._exit_buf)[:-1]

        enter_high = max(b.high for b in enter_prior)
        enter_low = min(b.low for b in enter_prior)
        exit_high = max(b.high for b in exit_prior)
        exit_low = min(b.low for b in exit_prior)
        exit_mid = (exit_high + exit_low) / 2.0

        # ATR expansion filter: current ATR must be above previous ATR.
        prev_atr = self._prev_atr
        self._prev_atr = atr
        atr_expanding = (not self.atr_filter) or (prev_atr is not None and atr > prev_atr)

        c = bar.close
        in_long = self._state == 1
        in_short = self._state == -1

        # --- Exits ---
        if in_long and c < exit_mid:
            self._state = 0
            return Signal.FLAT
        if in_short and c > exit_mid:
            self._state = 0
            return Signal.FLAT

        # --- Entries ---
        if c > enter_high and atr_expanding and self._state != 1:
            self._state = 1
            return Signal.BUY
        if c < enter_low and atr_expanding and self._state != -1:
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

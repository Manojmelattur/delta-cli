"""Price-action Pin Bar reversal strategy.

Classic pinbar (a.k.a. hammer / shooting star): long lower or upper wick,
small body, closing in the top/bottom third. Filtered by an EMA trend so
we only take pins that reject *against* an over-extended move.

Params:
  wick_ratio (float, 2.0)    min wick / body ratio
  body_frac (float, 0.33)    body must be within this fraction of total range
  ema_len (int, 50)          trend filter EMA length
  require_swing (bool, True) only fire at N-bar swing extreme
  swing (int, 5)             lookback for swing extreme
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class PinBar(Strategy):
    name = "price_action_pinbar"
    regime = "any"

    def on_start(self):
        self.wick_ratio = float(self.p("wick_ratio", 2.0))
        self.body_frac = float(self.p("body_frac", 0.33))
        self.ema_len = int(self.p("ema_len", 50))
        self.require_swing = bool(self.p("require_swing", True))
        self.swing = int(self.p("swing", 5))
        self.k = 2 / (self.ema_len + 1)
        self._init_state()

    def _init_state(self):
        self.ema: float | None = None
        # swing + 1: retain enough prior bars after excluding the current one.
        self.buf: deque[Bar] = deque(maxlen=self.swing + 1)
        self._warm = 0
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self.ema = bar.close if self.ema is None else (bar.close - self.ema) * self.k + self.ema
        self._warm += 1
        self.buf.append(bar)

        # Suppress signals until EMA has had a full ema_len bars to stabilise.
        if self._warm < self.ema_len:
            return Signal.HOLD

        rng = max(bar.high - bar.low, 1e-9)
        body = abs(bar.close - bar.open)
        upper_wick = max(bar.high - max(bar.close, bar.open), 0.0)
        lower_wick = max(min(bar.close, bar.open) - bar.low, 0.0)
        body_ok = body <= rng * self.body_frac

        is_bull_pin = (
            body_ok
            and lower_wick >= self.wick_ratio * max(body, 1e-9)
            and bar.close > bar.open
        )
        is_bear_pin = (
            body_ok
            and upper_wick >= self.wick_ratio * max(body, 1e-9)
            and bar.close < bar.open
        )

        # Exclude the current bar from the swing comparison to avoid
        # trivial self-confirmation.
        prior = list(self.buf)[:-1]
        at_swing_lo = (
            (not self.require_swing)
            or (len(prior) == self.swing and bar.low <= min(b.low for b in prior))
        )
        at_swing_hi = (
            (not self.require_swing)
            or (len(prior) == self.swing and bar.high >= max(b.high for b in prior))
        )

        # Trade pinbars against an over-extension: bull pin when price below EMA.
        if is_bull_pin and at_swing_lo and bar.close < self.ema and self._state != 1:
            self._state = 1
            return Signal.BUY
        if is_bear_pin and at_swing_hi and bar.close > self.ema and self._state != -1:
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

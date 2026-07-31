"""CCI (Commodity Channel Index) mean-reversion strategy.

Fires on extreme CCI readings and enters when CCI crosses back
through the threshold — confirming the reversal rather than
chasing the extreme.

Params:
    cci_len     (int,   default 20)   — CCI period
    threshold   (float, default 100)  — Extreme level (uses +/- threshold)
    exit_zero   (bool,  default True) — Exit when CCI crosses back through zero
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class CciReversion(Strategy):
    name = "cci_reversion"
    regime = "range"

    def on_start(self):
        self.cci_len = int(self.p("cci_len", 20))
        self.threshold = float(self.p("threshold", 100.0))
        self.exit_zero = bool(self.p("exit_zero", True))
        self._init_state()

    def _init_state(self):
        self._buf: deque[Bar] = deque(maxlen=self.cci_len)
        self._prev_cci: float | None = None
        self._armed_bull = False  # CCI was below -threshold
        self._armed_bear = False  # CCI was above +threshold
        self._state = 0           # 1 = long, -1 = short, 0 = flat

    def _calc_cci(self) -> float | None:
        if len(self._buf) < self.cci_len:
            return None
        typical = [(b.high + b.low + b.close) / 3.0 for b in self._buf]
        mean = sum(typical) / self.cci_len
        mean_dev = sum(abs(t - mean) for t in typical) / self.cci_len
        if mean_dev == 0:
            return 0.0
        return (typical[-1] - mean) / (0.015 * mean_dev)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._buf.append(bar)
        cci = self._calc_cci()
        if cci is None:
            return Signal.HOLD

        prev_cci = self._prev_cci
        self._prev_cci = cci

        if prev_cci is None:
            return Signal.HOLD

        in_long = self._state == 1
        in_short = self._state == -1

        # --- Exits ---
        if in_long and self.exit_zero and prev_cci < 0 and cci >= 0:
            self._state = 0
            return Signal.FLAT
        if in_short and self.exit_zero and prev_cci > 0 and cci <= 0:
            self._state = 0
            return Signal.FLAT

        # --- Arm when CCI reaches extreme ---
        if cci < -self.threshold:
            self._armed_bull = True
        if cci > self.threshold:
            self._armed_bear = True

        # --- Fire on cross back through threshold (reversal confirmation) ---
        if self._armed_bull and prev_cci < -self.threshold and cci >= -self.threshold:
            if self._state != 1:
                self._armed_bull = False
                self._armed_bear = False
                self._state = 1
                return Signal.BUY

        if self._armed_bear and prev_cci > self.threshold and cci <= self.threshold:
            if self._state != -1:
                self._armed_bear = False
                self._armed_bull = False
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

"""
Keltner Channel Squeeze Breakout Strategy.

Detects low-volatility compression (when Bollinger Bands lie inside Keltner Channels)
and fires momentum breakout trades when volatility expands outward.

Params:
    bb_period  (int,   default 20)  — Bollinger Band period
    bb_std     (float, default 2.0) — Bollinger Band standard deviation multiplier
    kc_period  (int,   default 20)  — Keltner Channel ATR period
    kc_mult    (float, default 1.5) — Keltner Channel ATR multiplier
"""
from __future__ import annotations

import math
from collections import deque

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext


class KeltnerSqueezeStrategy(Strategy):
    name = "keltner_squeeze"
    regime = "trend"

    def on_start(self):
        self.bb_period = int(self.p("bb_period", 20))
        self.bb_std = float(self.p("bb_std", 2.0))
        self.kc_period = int(self.p("kc_period", 20))
        self.kc_mult = float(self.p("kc_mult", 1.5))
        self._window = max(self.bb_period, self.kc_period) + 1
        self._init_state()

    def _init_state(self):
        self._bars: deque[Bar] = deque(maxlen=self._window)
        self._state = 0        # 1 = long, -1 = short, 0 = flat
        self._in_squeeze = False

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._bars.append(bar)

        # Wait for a full window before producing signals.
        if len(self._bars) < self._window:
            return Signal.HOLD

        # --- Bollinger Bands ---
        closes = [b.close for b in self._bars][-self.bb_period:]
        sma = sum(closes) / self.bb_period
        variance = sum((x - sma) ** 2 for x in closes) / self.bb_period
        std_dev = math.sqrt(variance)
        bb_upper = sma + self.bb_std * std_dev
        bb_lower = sma - self.bb_std * std_dev

        # --- Keltner Channels ---
        bars_kc = list(self._bars)[-self.kc_period - 1:]
        atr_sum = 0.0
        for i in range(1, len(bars_kc)):
            b, prev = bars_kc[i], bars_kc[i - 1]
            atr_sum += max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close))
        atr = atr_sum / self.kc_period
        kc_upper = sma + self.kc_mult * atr
        kc_lower = sma - self.kc_mult * atr

        # --- Squeeze detection ---
        # A squeeze is active when BB lies entirely inside the Keltner Channel.
        squeeze_now = bb_upper < kc_upper and bb_lower > kc_lower
        prev_in_squeeze = self._in_squeeze
        self._in_squeeze = squeeze_now

        prev_bar = list(self._bars)[-2]

        # --- Breakout signal (only valid when releasing from a squeeze) ---
        if prev_in_squeeze and not squeeze_now:
            if bar.close > kc_upper and prev_bar.close <= kc_upper and self._state != 1:
                self._state = 1
                return Signal.BUY
            elif bar.close < kc_lower and prev_bar.close >= kc_lower and self._state != -1:
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

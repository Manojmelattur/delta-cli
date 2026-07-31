"""Three-Bar Reversal strategy.

A three-bar reversal is a pure price-action pattern signalling exhaustion:
- Bullish: three consecutive lower closes followed by a close above the
  first bar's open (buying exhaustion absorbed).
- Bearish: three consecutive higher closes followed by a close below the
  first bar's open (selling exhaustion absorbed).

Filtered by an EMA so we only take reversals against an over-extended move.

Params:
    ema_len         (int,   default 50)  — Trend filter EMA length
    confirm_bars    (int,   default 2)   — Bars to wait for confirmation close
    min_move_pct    (float, default 0.1) — Min % move across the 3 bars
                                           (filters trivially small patterns)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


@dataclass
class _Pattern:
    direction: int    # 1 = bullish reversal setup, -1 = bearish
    trigger: float    # price level that confirms the reversal
    age: int = field(default=0)


class ThreeBarReversal(Strategy):
    name = "three_bar_reversal"
    regime = "any"

    def on_start(self):
        self.ema_len = int(self.p("ema_len", 50))
        self.confirm_bars = int(self.p("confirm_bars", 2))
        self.min_move_pct = float(self.p("min_move_pct", 0.1)) / 100.0
        self.k = 2 / (self.ema_len + 1)
        self._init_state()

    def _init_state(self):
        self._ema: float | None = None
        self._warm = 0
        self._buf: deque[Bar] = deque(maxlen=3)
        self._patterns: list[_Pattern] = []
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _detect_pattern(self) -> _Pattern | None:
        """Detect a three-bar reversal setup on the last 3 closed bars."""
        if len(self._buf) < 3:
            return None
        b0, b1, b2 = self._buf[0], self._buf[1], self._buf[2]

        # Bullish: three consecutive lower closes.
        if b1.close < b0.close and b2.close < b1.close:
            move = abs(b2.close - b0.close) / max(b0.close, 1e-9)
            if move >= self.min_move_pct:
                return _Pattern(direction=1, trigger=b0.open)

        # Bearish: three consecutive higher closes.
        if b1.close > b0.close and b2.close > b1.close:
            move = abs(b2.close - b0.close) / max(b0.close, 1e-9)
            if move >= self.min_move_pct:
                return _Pattern(direction=-1, trigger=b0.open)

        return None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        # EMA update.
        self._ema = (
            bar.close if self._ema is None
            else (bar.close - self._ema) * self.k + self._ema
        )
        self._warm += 1
        self._buf.append(bar)

        if self._warm < self.ema_len or len(self._buf) < 3:
            return Signal.HOLD

        ema = self._ema
        if ema is None:
            return Signal.HOLD

        # Detect new pattern on the last 3 bars.
        pattern = self._detect_pattern()
        if pattern is not None:
            self._patterns.append(pattern)

        # Age patterns and check confirmation close.
        signal = Signal.HOLD
        next_patterns: list[_Pattern] = []
        for p in self._patterns:
            p.age += 1
            if p.age > self.confirm_bars:
                continue  # expired — drop

            fired = False

            # Bullish reversal: close above first bar's open, price below EMA
            # (reversal against a downtrend over-extension).
            if (
                p.direction == 1
                and bar.close > p.trigger
                and bar.close < ema
                and self._state != 1
                and signal == Signal.HOLD
            ):
                self._state = 1
                signal = Signal.BUY
                fired = True

            # Bearish reversal: close below first bar's open, price above EMA
            # (reversal against an uptrend over-extension).
            elif (
                p.direction == -1
                and bar.close < p.trigger
                and bar.close > ema
                and self._state != -1
                and signal == Signal.HOLD
            ):
                self._state = -1
                signal = Signal.SELL
                fired = True

            if not fired:
                next_patterns.append(p)

        self._patterns = next_patterns
        return signal

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

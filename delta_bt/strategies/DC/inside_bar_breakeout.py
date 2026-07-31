"""Inside Bar Breakout strategy.

An inside bar is a bar whose high and low are completely contained
within the prior bar's range (the 'mother bar'). It signals
consolidation. Entry fires when price breaks out of the mother bar's
range on the following bars, confirmed by an EMA trend filter.

Params:
    ema_len         (int,   default 50)   — Trend filter EMA length
    breakout_bars   (int,   default 3)    — Max bars to wait for breakout
    min_body_ratio  (float, default 0.3)  — Mother bar body / range min ratio
                                            (filters weak indecision bars)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


@dataclass
class _Setup:
    mother_high: float
    mother_low: float
    direction: int   # 1 = bullish bias (mother bar bullish), -1 = bearish
    age: int = field(default=0)


class InsideBarBreakout(Strategy):
    name = "inside_bar_breakout"
    regime = "trend"

    def on_start(self):
        self.ema_len = int(self.p("ema_len", 50))
        self.breakout_bars = int(self.p("breakout_bars", 3))
        self.min_body_ratio = float(self.p("min_body_ratio", 0.3))
        self.k = 2 / (self.ema_len + 1)
        self._init_state()

    def _init_state(self):
        self._ema: float | None = None
        self._warm = 0
        self._prev_bar: Bar | None = None
        self._setups: list[_Setup] = []
        self._state = 0  # 1 = long, -1 = short, 0 = flat

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

        prev = self._prev_bar
        self._prev_bar = bar

        if prev is None or self._warm < self.ema_len:
            return Signal.HOLD

        ema = self._ema
        if ema is None:
            return Signal.HOLD

        # --- Detect inside bar ---
        # Current bar is inside the previous (mother) bar.
        is_inside = bar.high <= prev.high and bar.low >= prev.low
        if is_inside:
            mother_rng = max(prev.high - prev.low, 1e-9)
            mother_body = abs(prev.close - prev.open)
            body_ok = (mother_body / mother_rng) >= self.min_body_ratio
            if body_ok:
                direction = 1 if prev.close >= prev.open else -1
                self._setups.append(_Setup(
                    mother_high=prev.high,
                    mother_low=prev.low,
                    direction=direction,
                ))

        # --- Age setups and check breakout ---
        signal = Signal.HOLD
        next_setups: list[_Setup] = []
        for s in self._setups:
            s.age += 1
            if s.age > self.breakout_bars:
                continue  # expired — drop

            fired = False

            # Bullish breakout: close above mother high, EMA trend up, bias bullish.
            if (
                bar.close > s.mother_high
                and bar.close > ema
                and s.direction == 1
                and self._state != 1
                and signal == Signal.HOLD
            ):
                self._state = 1
                signal = Signal.BUY
                fired = True

            # Bearish breakout: close below mother low, EMA trend down, bias bearish.
            elif (
                bar.close < s.mother_low
                and bar.close < ema
                and s.direction == -1
                and self._state != -1
                and signal == Signal.HOLD
            ):
                self._state = -1
                signal = Signal.SELL
                fired = True

            if not fired:
                next_setups.append(s)

        self._setups = next_setups
        return signal

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

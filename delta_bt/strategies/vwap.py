"""VWAP mean-reversion / trend strategy (session VWAP, resets daily UTC).

Params: mode("trend"|"revert"), band_bps(20).
- trend  : long when close > VWAP + band, short when close < VWAP - band
- revert : long when close < VWAP - band, short when close > VWAP + band
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Vwap(Strategy):
    name = "vwap"
    regime = "any"

    def on_start(self):
        self.mode = self.p("mode", "trend")
        self.band = float(self.p("band_bps", 20)) / 10_000
        self._init_state()

    def _init_state(self):
        self._day = None
        self._pv = 0.0
        self._v = 0.0
        self._state = 0  # 1 = long, -1 = short, 0 = flat
        self._prev_close: float | None = None
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        d = bar.ts.date()
        if d != self._day:
            self._day = d
            self._pv = 0.0
            self._v = 0.0
            self._prev_close = None
            self._prev_upper = None
            self._prev_lower = None

        typical = (bar.high + bar.low + bar.close) / 3
        vol = bar.volume if bar.volume > 0 else 1.0
        self._pv += typical * vol
        self._v += vol
        vwap = self._pv / self._v
        upper = vwap * (1 + self.band)
        lower = vwap * (1 - self.band)
        c = bar.close

        pc = self._prev_close
        pu = self._prev_upper
        pl = self._prev_lower
        self._prev_close = c
        self._prev_upper = upper
        self._prev_lower = lower

        if pc is None or pu is None or pl is None:
            return Signal.HOLD

        # Edge-triggered: require a fresh cross on the last closed bar.
        crossed_up = pc <= pu and c > upper
        crossed_down = pc >= pl and c < lower

        if self.mode == "trend":
            if crossed_up and self._state != 1:
                self._state = 1
                return Signal.BUY
            if crossed_down and self._state != -1:
                self._state = -1
                return Signal.SELL
        else:
            if crossed_down and self._state != 1:
                self._state = 1
                return Signal.BUY
            if crossed_up and self._state != -1:
                self._state = -1
                return Signal.SELL

        return Signal.HOLD

    def intent(self) -> Signal:
        if self._prev_upper is None or self._prev_lower is None or self._prev_close is None:
            return Signal.HOLD
        c = self._prev_close
        if self.mode == "trend":
            if c > self._prev_upper:
                return Signal.BUY
            if c < self._prev_lower:
                return Signal.SELL
        else:
            if c < self._prev_lower:
                return Signal.BUY
            if c > self._prev_upper:
                return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

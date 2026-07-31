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
        self._day = None
        self._pv = 0.0
        self._v = 0.0
        self._state = 0
        self._prev_close = None
        self._prev_upper = None
        self._prev_lower = None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        d = bar.ts.date()
        if d != self._day:
            self._day = d; self._pv = 0.0; self._v = 0.0
            self._prev_close = None; self._prev_upper = None; self._prev_lower = None
        typical = (bar.high + bar.low + bar.close) / 3
        vol = bar.volume if bar.volume > 0 else 1.0
        self._pv += typical * vol
        self._v += vol
        vwap = self._pv / self._v
        upper = vwap * (1 + self.band); lower = vwap * (1 - self.band)
        c = bar.close

        # Reset self-latch when flat so re-entry after SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        pc, pu, pl = self._prev_close, self._prev_upper, self._prev_lower
        self._prev_close, self._prev_upper, self._prev_lower = c, upper, lower
        if pc is None or pu is None or pl is None:
            return Signal.HOLD

        # Edge-triggered: require a fresh cross on the last closed bar.
        crossed_up = pc <= pu and c > upper
        crossed_down = pc >= pl and c < lower

        if self.mode == "trend":
            if crossed_up and self._state != 1: self._state = 1; return Signal.BUY
            if crossed_down and self._state != -1: self._state = -1; return Signal.SELL
        else:
            if crossed_down and self._state != 1: self._state = 1; return Signal.BUY
            if crossed_up and self._state != -1: self._state = -1; return Signal.SELL
        return Signal.HOLD

    def intent(self, bar: Bar):
        if self._v == 0:
            return None
        vwap = self._pv / self._v
        upper = vwap * (1 + self.band); lower = vwap * (1 - self.band)
        c = bar.close
        if self.mode == "trend":
            if c > upper: return Signal.BUY
            if c < lower: return Signal.SELL
        else:
            if c < lower: return Signal.BUY
            if c > upper: return Signal.SELL
        return None

"""SMC order-block strategy (simplified).

An order block = the last opposing candle before a strong impulsive move.
- Bullish OB: last down-candle before an up-move that closes above its high
- Bearish OB: last up-candle before a down-move that closes below its low

Entry when price returns to (wicks into) the OB body.
Params: impulse_bars(3), impulse_mult(1.5) (impulse body vs avg body).
"""
from __future__ import annotations

from collections import deque
from statistics import fmean

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class SmcOrderBlock(Strategy):
    name = "smc_ob"

    regime = "any"
    def on_start(self):
        self.imp = int(self.p("impulse_bars", 3))
        self.mult = float(self.p("impulse_mult", 1.5))
        self.buf: deque[Bar] = deque(maxlen=self.imp + 2)
        self.bodies: deque[float] = deque(maxlen=20)
        self.obs: list = []   # (side, lo, hi, age)
        self.max_age = int(self.p("max_age", 50))
        

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self.bodies.append(abs(bar.close - bar.open))
        self.buf.append(bar)
        avg_body = fmean(self.bodies) if len(self.bodies) >= 5 else 0

        # detect OB using buffered impulse
        if avg_body > 0 and len(self.buf) == self.buf.maxlen:
            candidate = self.buf[0]  # potential OB candle
            impulse = list(self.buf)[1:]
            up_impulse = all(b.close > b.open for b in impulse) and \
                         sum(b.close - b.open for b in impulse) > self.mult * avg_body
            down_impulse = all(b.close < b.open for b in impulse) and \
                           sum(b.open - b.close for b in impulse) > self.mult * avg_body
            if up_impulse and candidate.close < candidate.open:
                self.obs.append(["BUY", min(candidate.open, candidate.close),
                                 max(candidate.open, candidate.close), 0])
            elif down_impulse and candidate.close > candidate.open:
                self.obs.append(["SELL", min(candidate.open, candidate.close),
                                 max(candidate.open, candidate.close), 0])

        for ob in list(self.obs):
            side, lo, hi, age = ob
            ob[3] += 1
            if ob[3] > self.max_age:
                self.obs.remove(ob); continue
            if lo <= bar.close <= hi:
                self.obs.remove(ob)
                if side == "BUY":
                    return Signal.BUY
                if side == "SELL":
                    return Signal.SELL
        return Signal.HOLD

"""SMC Order-Block + FVG Confluence strategy.

Enters only when price retests an order-block that ALSO overlaps a
Fair-Value-Gap in the same direction — a common high-probability SMC setup.

Logic:
- Detect bullish/bearish order blocks (last opposing candle before an
  impulsive move of `imp_bars` bars with combined body > `imp_mult` * avg body).
- Detect 3-bar FVGs.
- When an OB and an FVG on the same side overlap in price, mark that zone.
- BUY/SELL on the first bar whose close re-enters the confluence zone.

Params:
  imp_bars (int, 3)         bars in the impulse leg
  imp_mult (float, 1.5)     impulse body vs avg body
  fvg_lookback (int, 40)    how long an FVG stays valid
  max_age (int, 60)         how long a confluence zone stays valid
"""
from __future__ import annotations

from collections import deque
from statistics import fmean

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class SmcOrderBlockFvg(Strategy):
    name = "smc_ob_fvg"

    regime = "any"
    def on_start(self):
        self.imp = int(self.p("imp_bars", 3))
        self.mult = float(self.p("imp_mult", 1.5))
        self.fvg_lb = int(self.p("fvg_lookback", 40))
        self.max_age = int(self.p("max_age", 60))
        self.buf: deque[Bar] = deque(maxlen=self.imp + 2)
        self.body_hist: deque[float] = deque(maxlen=20)
        self.bars3: deque[Bar] = deque(maxlen=3)
        self.obs: list = []      # [side, lo, hi, age]
        self.fvgs: list = []     # [side, lo, hi, age]
        self.zones: list = []    # [side, lo, hi, age]
        self._state = 0

    def _detect_ob(self):
        if len(self.body_hist) < 5 or len(self.buf) < self.buf.maxlen:
            return
        avg_body = fmean(self.body_hist)
        if avg_body <= 0:
            return
        candidate = self.buf[0]
        impulse = list(self.buf)[1:]
        up = all(b.close > b.open for b in impulse) and \
            sum(b.close - b.open for b in impulse) > self.mult * avg_body
        dn = all(b.close < b.open for b in impulse) and \
            sum(b.open - b.close for b in impulse) > self.mult * avg_body
        if up and candidate.close < candidate.open:
            self.obs.append(["BUY", min(candidate.open, candidate.close),
                             max(candidate.open, candidate.close), 0])
        elif dn and candidate.close > candidate.open:
            self.obs.append(["SELL", min(candidate.open, candidate.close),
                             max(candidate.open, candidate.close), 0])

    def _detect_fvg(self):
        if len(self.bars3) < 3:
            return
        b2, b1, b0 = self.bars3[0], self.bars3[1], self.bars3[2]
        if b0.low > b2.high:
            self.fvgs.append(["BUY", b2.high, b0.low, 0])
        elif b0.high < b2.low:
            self.fvgs.append(["SELL", b0.high, b2.low, 0])

    def _refresh_zones(self):
        for ob in self.obs:
            for fv in self.fvgs:
                if ob[0] != fv[0]:
                    continue
                lo = max(ob[1], fv[1]); hi = min(ob[2], fv[2])
                if lo < hi:
                    self.zones.append([ob[0], lo, hi, 0])

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0
        self.body_hist.append(abs(bar.close - bar.open))
        self.buf.append(bar)
        self.bars3.append(bar)

        prev_obs = len(self.obs); prev_fvgs = len(self.fvgs)
        self._detect_ob()
        self._detect_fvg()
        if len(self.obs) != prev_obs or len(self.fvgs) != prev_fvgs:
            self._refresh_zones()

        # age lists
        for lst, cap in ((self.obs, self.max_age),
                         (self.fvgs, self.fvg_lb),
                         (self.zones, self.max_age)):
            for it in list(lst):
                it[3] += 1
                if it[3] > cap:
                    lst.remove(it)

        # check zone retest
        for z in list(self.zones):
            side, lo, hi, _ = z
            if lo <= bar.close <= hi:
                self.zones.remove(z)
                if side == "BUY" and self._state != 1:
                    self._state = 1; return Signal.BUY
                if side == "SELL" and self._state != -1:
                    self._state = -1; return Signal.SELL
        return Signal.HOLD

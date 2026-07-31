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
        self._init_state()

    def _init_state(self):
        self.buf: deque[Bar] = deque(maxlen=self.imp + 2)
        self.body_hist: deque[float] = deque(maxlen=20)
        self.bars3: deque[Bar] = deque(maxlen=3)
        self.obs: list = []    # [side, lo, hi, age]
        self.fvgs: list = []   # [side, lo, hi, age]
        self.zones: list = []  # [side, lo, hi, age]
        self._state = 0        # 1 = long, -1 = short, 0 = flat

    def _age_list(self, lst: list, cap: int) -> list:
        """Increment age of every entry and drop expired ones."""
        surviving = []
        for it in lst:
            it[3] += 1
            if it[3] <= cap:
                surviving.append(it)
        return surviving

    def _detect_ob(self) -> list:
        """Return newly detected OBs this bar (empty list if none)."""
        if len(self.body_hist) < 5 or len(self.buf) < self.imp + 2:
            return []
        avg_body = fmean(self.body_hist)
        if avg_body <= 0:
            return []
        candidate = self.buf[0]
        impulse = list(self.buf)[1:]
        up = (
            all(b.close > b.open for b in impulse)
            and sum(b.close - b.open for b in impulse) > self.mult * avg_body
        )
        dn = (
            all(b.close < b.open for b in impulse)
            and sum(b.open - b.close for b in impulse) > self.mult * avg_body
        )
        new_obs = []
        if up and candidate.close < candidate.open:
            new_obs.append(["BUY", min(candidate.open, candidate.close),
                            max(candidate.open, candidate.close), 0])
        elif dn and candidate.close > candidate.open:
            new_obs.append(["SELL", min(candidate.open, candidate.close),
                            max(candidate.open, candidate.close), 0])
        return new_obs

    def _detect_fvg(self) -> list:
        """Return newly detected FVGs this bar (empty list if none)."""
        if len(self.bars3) < 3:
            return []
        b2, b1, b0 = self.bars3[0], self.bars3[1], self.bars3[2]
        if b0.low > b2.high:
            return [["BUY", b2.high, b0.low, 0]]
        if b0.high < b2.low:
            return [["SELL", b0.high, b2.low, 0]]
        return []

    def _build_new_zones(self, new_obs: list, new_fvgs: list) -> list:
        """
        Create confluence zones only from newly detected entries crossed
        against the full existing lists — avoids re-pairing old entries.
        """
        new_zones = []
        # New OBs crossed against all existing + new FVGs.
        for ob in new_obs:
            for fv in self.fvgs + new_fvgs:
                if ob[0] != fv[0]:
                    continue
                lo = max(ob[1], fv[1])
                hi = min(ob[2], fv[2])
                if lo < hi:
                    new_zones.append([ob[0], lo, hi, 0])
        # New FVGs crossed against existing OBs only (new OBs already covered above).
        for fv in new_fvgs:
            for ob in self.obs:
                if ob[0] != fv[0]:
                    continue
                lo = max(ob[1], fv[1])
                hi = min(ob[2], fv[2])
                if lo < hi:
                    new_zones.append([ob[0], lo, hi, 0])
        return new_zones

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self.body_hist.append(abs(bar.close - bar.open))
        self.buf.append(bar)
        self.bars3.append(bar)

        new_obs = self._detect_ob()
        new_fvgs = self._detect_fvg()
        new_zones = self._build_new_zones(new_obs, new_fvgs)

        self.obs += new_obs
        self.fvgs += new_fvgs
        self.zones += new_zones

        # Age all lists and drop expired entries.
        self.obs = self._age_list(self.obs, self.max_age)
        self.fvgs = self._age_list(self.fvgs, self.fvg_lb)
        self.zones = self._age_list(self.zones, self.max_age)

        # Check zone retest.
        surviving_zones = []
        signal = Signal.HOLD
        for z in self.zones:
            side, lo, hi, _ = z
            if signal == Signal.HOLD and lo <= bar.close <= hi:
                if side == "BUY" and self._state != 1:
                    self._state = 1
                    signal = Signal.BUY
                elif side == "SELL" and self._state != -1:
                    self._state = -1
                    signal = Signal.SELL
                # Drop the consumed zone regardless of whether state guard fired.
            else:
                surviving_zones.append(z)
        self.zones = surviving_zones
        return signal

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

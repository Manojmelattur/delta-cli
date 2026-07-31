"""Volume Profile + VWAP strategy.

Builds an intraday volume profile (Point of Control, Value Area High/Low)
and combines it with session VWAP. Enters when price retests a profile
level that aligns with the VWAP direction.

Logic:
- POC  : price level with the highest volume in the session.
- VAH  : Value Area High — upper boundary of the 70% volume value area.
- VAL  : Value Area Low  — lower boundary of the 70% volume value area.
- Entry: BUY  when price retests VAL or POC from above and close > VWAP.
         SELL when price retests VAH or POC from below and close < VWAP.

Params:
    tick_size    (float, default 10.0)  — Price bucket width for profile
    value_area   (float, default 0.70)  — Fraction of volume inside value area
    touch_pct    (float, default 0.1)   — % tolerance for level touch detection
"""
from __future__ import annotations

from collections import defaultdict

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class VolumeProfileVwap(Strategy):
    name = "volume_profile_vwap"
    regime = "range"

    def on_start(self):
        self.tick_size = float(self.p("tick_size", 10.0))
        self.value_area = float(self.p("value_area", 0.70))
        self.touch_pct = float(self.p("touch_pct", 0.1)) / 100.0
        self._init_state()

    def _init_state(self):
        self._day = None
        self._pv = 0.0
        self._v = 0.0
        self._profile: dict[int, float] = defaultdict(float)
        self._poc: float | None = None
        self._vah: float | None = None
        self._val: float | None = None
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _bucket(self, price: float) -> int:
        """Map a price to its profile bucket index."""
        return int(price / self.tick_size)

    def _bucket_price(self, bucket: int) -> float:
        """Return the mid-price of a bucket."""
        return (bucket + 0.5) * self.tick_size

    def _build_profile(self):
        """Compute POC, VAH, VAL from the current session profile."""
        if not self._profile:
            return
        total_vol = sum(self._profile.values())
        target = total_vol * self.value_area

        # POC: bucket with highest volume.
        poc_bucket = max(self._profile, key=lambda b: self._profile[b])
        self._poc = self._bucket_price(poc_bucket)

        # Value area: expand outward from POC until target volume is reached.
        sorted_buckets = sorted(self._profile.keys())
        poc_idx = sorted_buckets.index(poc_bucket)
        lo_idx = hi_idx = poc_idx
        accumulated = self._profile[poc_bucket]

        while accumulated < target:
            can_expand_lo = lo_idx > 0
            can_expand_hi = hi_idx < len(sorted_buckets) - 1
            if not can_expand_lo and not can_expand_hi:
                break
            vol_lo = self._profile[sorted_buckets[lo_idx - 1]] if can_expand_lo else 0.0
            vol_hi = self._profile[sorted_buckets[hi_idx + 1]] if can_expand_hi else 0.0
            if vol_hi >= vol_lo and can_expand_hi:
                hi_idx += 1
                accumulated += self._profile[sorted_buckets[hi_idx]]
            elif can_expand_lo:
                lo_idx -= 1
                accumulated += self._profile[sorted_buckets[lo_idx]]
            else:
                hi_idx += 1
                accumulated += self._profile[sorted_buckets[hi_idx]]

        self._val = self._bucket_price(sorted_buckets[lo_idx])
        self._vah = self._bucket_price(sorted_buckets[hi_idx])

    def _near(self, price: float, level: float) -> bool:
        """Return True if price is within touch_pct of level."""
        return abs(price - level) <= level * self.touch_pct

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        # Session reset.
        d = bar.ts.date()
        if d != self._day:
            self._day = d
            self._pv = 0.0
            self._v = 0.0
            self._profile = defaultdict(float)
            self._poc = None
            self._vah = None
            self._val = None

        vol = bar.volume if bar.volume > 0 else 1.0
        typical = (bar.high + bar.low + bar.close) / 3.0

        # Accumulate VWAP.
        self._pv += typical * vol
        self._v += vol
        vwap = self._pv / self._v

        # Accumulate volume profile.
        self._profile[self._bucket(typical)] += vol
        self._build_profile()

        poc = self._poc
        vah = self._vah
        val = self._val

        if poc is None or vah is None or val is None:
            return Signal.HOLD

        c = bar.close

        # BUY: price retests VAL or POC from above, close is above VWAP.
        if c > vwap:
            if self._near(c, val) or self._near(c, poc):
                if self._state != 1:
                    self._state = 1
                    return Signal.BUY

        # SELL: price retests VAH or POC from below, close is below VWAP.
        if c < vwap:
            if self._near(c, vah) or self._near(c, poc):
                if self._state != -1:
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

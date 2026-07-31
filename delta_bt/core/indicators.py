"""Streaming technical indicators used by the engine (not by strategies).

Kept intentionally tiny — one class per indicator, `.update(bar)` returns the
latest value (or `None` while warming up).
"""
from __future__ import annotations

from typing import Optional

from .types import Bar


class ADX:
    """Wilder's Average Directional Index, computed incrementally.

    ADX measures *trend strength* (not direction):
      - ADX  < 20 → range / chop
      - ADX >= 20 → trending
      - ADX >= 40 → very strong trend

    Uses Wilder's RMA smoothing (equivalent to EMA with alpha = 1/period),
    which is the definition every charting package uses.
    """

    def __init__(self, period: int = 14):
        self.n = max(2, int(period))
        self.alpha = 1.0 / self.n
        self._prev: Optional[Bar] = None
        self._tr = 0.0
        self._pdm = 0.0
        self._mdm = 0.0
        self._adx: Optional[float] = None
        self._warm = 0

    def update(self, bar: Bar) -> Optional[float]:
        if self._prev is None:
            self._prev = bar
            return None
        up = bar.high - self._prev.high
        dn = self._prev.low - bar.low
        pdm = up if (up > dn and up > 0) else 0.0
        mdm = dn if (dn > up and dn > 0) else 0.0
        tr = max(
            bar.high - bar.low,
            abs(bar.high - self._prev.close),
            abs(bar.low - self._prev.close),
        )
        # Wilder smoothing
        self._tr  = self._tr  + self.alpha * (tr  - self._tr)
        self._pdm = self._pdm + self.alpha * (pdm - self._pdm)
        self._mdm = self._mdm + self.alpha * (mdm - self._mdm)
        self._prev = bar
        self._warm += 1

        if self._tr <= 0 or self._warm < self.n:
            return None
        pdi = 100.0 * self._pdm / self._tr
        mdi = 100.0 * self._mdm / self._tr
        denom = pdi + mdi
        if denom <= 0:
            return self._adx
        dx = 100.0 * abs(pdi - mdi) / denom
        self._adx = dx if self._adx is None else (self._adx + self.alpha * (dx - self._adx))
        return self._adx

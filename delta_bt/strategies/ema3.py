"""Triple EMA trend strategy.

Params: fast(9), mid(21), slow(55).
Long  when fast > mid > slow (bullish alignment).
Short when fast < mid < slow (bearish alignment).
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class ThreeEma(Strategy):
    name   = "ema3"
    regime = "trend"

    def __init__(self, params: Optional[dict] = None):
        super().__init__(params if params is not None else {})
        self._initialised = False

    def _init_state(self) -> None:
        """Initialise or reset all strategy state."""
        self.f  = int(self.p("fast", 9))
        self.m  = int(self.p("mid",  21))
        self.s  = int(self.p("slow", 55))

        self.kf = 2 / (self.f + 1)
        self.km = 2 / (self.m + 1)
        self.ks = 2 / (self.s + 1)

        # Fix 1: use deques to collect seed bars for SMA initialisation
        self._seed_f: deque = deque(maxlen=self.f)
        self._seed_m: deque = deque(maxlen=self.m)
        self._seed_s: deque = deque(maxlen=self.s)

        self.ef: Optional[float] = None
        self.em: Optional[float] = None
        self.es: Optional[float] = None

        self._warm:  int = 0
        self._state: int = 0   # 1=long, -1=short, 0=flat
        self._initialised = True

    def on_start(self) -> None:
        self._init_state()

    def _ensure_init(self) -> None:
        """Guarantee state exists even if on_start was never called."""
        if not self._initialised:
            self._init_state()

    def _is_flat(self, ctx: StrategyContext) -> bool:
        """Check if position is flat using open_side with qty fallback."""
        pos       = ctx.position
        open_side = getattr(pos, "open_side", None)
        if open_side is not None:
            return not open_side
        return getattr(pos, "qty", 0) == 0

    def _update_emas(self, px: float) -> bool:
        """Update all three EMAs with new price.

        Fix 1: seeds each EMA with SMA of first `period` bars.
        Returns True once all three EMAs are fully warmed up.
        """
        self._seed_f.append(px)
        self._seed_m.append(px)
        self._seed_s.append(px)
        self._warm += 1

        # Fast EMA
        if self.ef is None:
            if len(self._seed_f) >= self.f:
                self.ef = sum(self._seed_f) / self.f
        else:
            self.ef = (px - self.ef) * self.kf + self.ef

        # Mid EMA
        if self.em is None:
            if len(self._seed_m) >= self.m:
                self.em = sum(self._seed_m) / self.m
        else:
            self.em = (px - self.em) * self.km + self.em

        # Slow EMA
        if self.es is None:
            if len(self._seed_s) >= self.s:
                self.es = sum(self._seed_s) / self.s
        else:
            self.es = (px - self.es) * self.ks + self.es

        # Fix 2: return True only when all three are seeded
        return self.ef is not None and self.em is not None and self.es is not None

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self._ensure_init()

        # Fix 6: reset state when position is externally closed
        # so the strategy can re-enter on the next valid alignment
        if self._is_flat(ctx) and self._state != 0:
            self._state = 0

        px    = bar.close
        ready = self._update_emas(px)

        if not ready:
            return Signal.HOLD

        # Fix 3: explicit None guard so type checker narrows to float
        if self.ef is None or self.em is None or self.es is None:
            return Signal.HOLD

        if self.ef > self.em > self.es and self._state != 1:
            self._state = 1
            return Signal.BUY

        if self.ef < self.em < self.es and self._state != -1:
            self._state = -1
            return Signal.SELL

        return Signal.HOLD

    def intent(self, bar: Bar) -> Optional[Signal]:
        """Fix 4: return current directional bias from EMA alignment.

        Projects all three EMAs forward with bar.close without
        mutating stored state so repeated calls are safe.
        """
        self._ensure_init()

        if self.ef is None or self.em is None or self.es is None:
            return Signal.HOLD

        px       = bar.close
        proj_ef  = (px - self.ef) * self.kf + self.ef
        proj_em  = (px - self.em) * self.km + self.em
        proj_es  = (px - self.es) * self.ks + self.es

        if proj_ef > proj_em > proj_es:
            return Signal.BUY
        if proj_ef < proj_em < proj_es:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self) -> None:
        """Fix 5: reset all state so backtest reruns start clean."""
        self._initialised = False

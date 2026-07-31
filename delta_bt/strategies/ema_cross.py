from __future__ import annotations

from collections import deque
from typing import Optional

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class EmaCross(Strategy):
    name   = "ema_cross"
    regime = "trend"

    def __init__(self, params: Optional[dict] = None):
        # Fix: use Optional[dict] type hint and always pass a dict to super
        super().__init__(params if params is not None else {})
        self._initialised = False

    def _init_state(self):
        """Initialise or reset all strategy state."""
        self.fast  = int(self.p("fast", 9))
        self.slow  = int(self.p("slow", 21))
        self.k_f   = 2 / (self.fast + 1)
        self.k_s   = 2 / (self.slow + 1)

        self._seed_f: deque = deque(maxlen=self.fast)
        self._seed_s: deque = deque(maxlen=self.slow)

        self.ema_f: Optional[float] = None
        self.ema_s: Optional[float] = None

        self._prev_diff: Optional[float] = None
        self._warm: int    = 0
        self._initialised  = True

    def on_start(self):
        self._init_state()

    def _ensure_init(self):
        """Guarantee state exists even if on_start was never called."""
        if not self._initialised:
            self._init_state()

    def _update_emas(self, px: float) -> bool:
        """Update EMA values with new price.

        Seeds EMA with SMA of first `period` bars for accuracy.
        Returns True once both EMAs are fully warmed up.
        """
        self._seed_f.append(px)
        self._seed_s.append(px)
        self._warm += 1

        # Update or seed fast EMA
        if self.ema_f is None:
            if len(self._seed_f) >= self.fast:
                self.ema_f = sum(self._seed_f) / self.fast
        else:
            self.ema_f = (px - self.ema_f) * self.k_f + self.ema_f

        # Update or seed slow EMA
        if self.ema_s is None:
            if len(self._seed_s) >= self.slow:
                self.ema_s = sum(self._seed_s) / self.slow
        else:
            self.ema_s = (px - self.ema_s) * self.k_s + self.ema_s

        # Explicit bool return — type checker can verify this is always reached
        return self.ema_f is not None and self.ema_s is not None


    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self._ensure_init()

        px    = bar.close
        ready = self._update_emas(px)

        if not ready:
            return Signal.HOLD

        # Explicit None guard so type checker knows both are float here
        if self.ema_f is None or self.ema_s is None:
            return Signal.HOLD

        diff = self.ema_f - self.ema_s  # both are float — no type error
        sig  = Signal.HOLD

        if self._prev_diff is not None:
            if self._prev_diff <= 0 < diff:
                sig = Signal.BUY
            elif self._prev_diff >= 0 > diff:
                sig = Signal.SELL

        self._prev_diff = diff
        return sig


    def on_stop(self):
        """Reset all state so backtest reruns start clean."""
        self._initialised = False

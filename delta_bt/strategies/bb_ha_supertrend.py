"""Bollinger Bands + Heikin-Ashi + Supertrend confluence.

Params: bb_len(20), bb_mult(2), atr_len(10), st_mult(3),
        exit_on_ha_flip(true), allow_short(true), pierce_lookback(3)
Long: recent pierce below BB lower + close back above lower + HA bullish + ST up.
Short: recent pierce above BB upper + close back below upper + HA bearish + ST down.
Exit: Supertrend flips against position, or HA color flips (when enabled).
"""
from __future__ import annotations

from collections import deque
import math

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal, Side


class BbHaSupertrend(Strategy):
    name = "bb_ha_supertrend"
    regime = "trend"

    def on_start(self):
        self.bb_len = int(self.p("bb_len", 20))
        self.bb_mult = float(self.p("bb_mult", 2))
        self.atr_len = int(self.p("atr_len", 10))
        self.st_mult = float(self.p("st_mult", 3))
        self.exit_on_ha_flip = bool(self.p("exit_on_ha_flip", True))
        self.allow_short = bool(self.p("allow_short", True))
        self.pierce_lookback = int(self.p("pierce_lookback", 3))
        self._init_state()

    def _init_state(self):
        self._closes: deque[float] = deque(maxlen=self.bb_len + 2)
        self._ha_open_prev: float | None = None
        self._ha_close_prev: float | None = None
        self._ha_color_prev = 0
        self._prev_bar: Bar | None = None
        self._atr = 0.0
        self._warm = 0
        self._upper = float("inf")
        self._lower = float("-inf")
        self._st_dir = 0
        self._st_prev_dir = 0
        self._bb_mid: float | None = None
        self._bb_up: float | None = None
        self._bb_lo: float | None = None
        self._upper_pierces: deque[int] = deque(maxlen=self.pierce_lookback)
        self._lower_pierces: deque[int] = deque(maxlen=self.pierce_lookback)
        self._last_reason = ""
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        # --- Heikin-Ashi ---
        ha_close = (bar.open + bar.high + bar.low + bar.close) / 4
        if self._ha_open_prev is None or self._ha_close_prev is None:
            ha_open = (bar.open + bar.close) / 2
        else:
            ha_open = (self._ha_open_prev + self._ha_close_prev) / 2
        ha_color = 1 if ha_close > ha_open else (-1 if ha_close < ha_open else 0)
        ha_flipped = (
            self._ha_color_prev != 0
            and ha_color != 0
            and ha_color != self._ha_color_prev
        )
        self._ha_open_prev = ha_open
        self._ha_close_prev = ha_close

        # --- Supertrend ATR (Wilder's smoothing) ---
        tr = bar.high - bar.low
        if self._prev_bar is not None:
            tr = max(
                tr,
                abs(bar.high - self._prev_bar.close),
                abs(bar.low - self._prev_bar.close),
            )
        self._warm += 1
        if self._warm <= self.atr_len:
            self._atr = self._atr + (tr - self._atr) / self._warm
        else:
            self._atr = (self._atr * (self.atr_len - 1) + tr) / self.atr_len

        mid = (bar.high + bar.low) / 2
        upper_basic = mid + self.st_mult * self._atr
        lower_basic = mid - self.st_mult * self._atr

        if self._upper != float("inf"):
            self._upper = (
                upper_basic
                if upper_basic < self._upper or bar.close > self._upper
                else self._upper
            )
            self._lower = (
                lower_basic
                if lower_basic > self._lower or bar.close < self._lower
                else self._lower
            )
        else:
            self._upper = upper_basic
            self._lower = lower_basic

        self._st_prev_dir = self._st_dir
        if bar.close > self._upper:
            self._st_dir = 1
        elif bar.close < self._lower:
            self._st_dir = -1

        self._prev_bar = bar

        # --- Bollinger Bands ---
        self._closes.append(bar.close)
        bb_mid: float | None = None
        bb_up: float | None = None
        bb_lo: float | None = None
        if len(self._closes) >= self.bb_len:
            bb_window = list(self._closes)[-self.bb_len:]
            mean = sum(bb_window) / self.bb_len
            var = sum((x - mean) ** 2 for x in bb_window) / self.bb_len
            sd = math.sqrt(var)
            bb_mid = mean
            bb_up = mean + self.bb_mult * sd
            bb_lo = mean - self.bb_mult * sd
        self._bb_mid = bb_mid
        self._bb_up = bb_up
        self._bb_lo = bb_lo

        self._ha_color_prev = ha_color

        # Suppress signals until ATR is fully seeded and BB window is full.
        if self._warm <= self.atr_len or bb_mid is None:
            self._last_reason = "warmup"
            return Signal.HOLD

        in_long = ctx.position.is_open and ctx.position.side == Side.LONG
        in_short = ctx.position.is_open and ctx.position.side == Side.SHORT

        # --- Exits ---
        if in_long:
            if self._st_dir == -1 and self._st_prev_dir != -1:
                self._state = 0
                self._last_reason = "exit: supertrend flip down"
                return Signal.FLAT
            if self.exit_on_ha_flip and ha_flipped and ha_color == -1:
                self._state = 0
                self._last_reason = "exit: HA color flip to bearish"
                return Signal.FLAT
            return Signal.HOLD

        if in_short:
            if self._st_dir == 1 and self._st_prev_dir != 1:
                self._state = 0
                self._last_reason = "exit: supertrend flip up"
                return Signal.FLAT
            if self.exit_on_ha_flip and ha_flipped and ha_color == 1:
                self._state = 0
                self._last_reason = "exit: HA color flip to bullish"
                return Signal.FLAT
            return Signal.HOLD

        # --- Entries: BB pierce + reject + HA color + Supertrend ---
        up_pierce = bb_up is not None and bar.high > bb_up
        lo_pierce = bb_lo is not None and bar.low < bb_lo
        self._upper_pierces.append(1 if up_pierce else 0)
        self._lower_pierces.append(1 if lo_pierce else 0)
        recent_upper_pierce = any(v == 1 for v in self._upper_pierces)
        recent_lower_pierce = any(v == 1 for v in self._lower_pierces)
        rejected_upper = recent_upper_pierce and bb_up is not None and bar.close < bb_up
        rejected_lower = recent_lower_pierce and bb_lo is not None and bar.close > bb_lo

        if ha_color == 1 and rejected_lower and self._st_dir == 1 and self._state != 1:
            self._state = 1
            self._last_reason = "long: BB lower pierce+reject + HA bull + ST up"
            return Signal.BUY

        if (
            self.allow_short
            and ha_color == -1
            and rejected_upper
            and self._st_dir == -1
            and self._state != -1
        ):
            self._state = -1
            self._last_reason = "short: BB upper pierce+reject + HA bear + ST down"
            return Signal.SELL

        self._last_reason = (
            f"wait (ha={ha_color} upP={int(recent_upper_pierce)} "
            f"loP={int(recent_lower_pierce)} st={self._st_dir})"
        )
        return Signal.HOLD

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

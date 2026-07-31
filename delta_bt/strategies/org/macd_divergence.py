"""MACD histogram divergence strategy.

Params: fast(12), slow(26), signal(9), pivot(3), lookback(60)
Bullish divergence: price lower low + histogram higher low -> arm BUY.
Fires when histogram crosses above zero after arming.
Bearish divergence: price higher high + histogram lower high -> arm SELL.
Fires when histogram crosses below zero after arming.
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class MacdDivergence(Strategy):
    name = "macd_divergence"

    regime = "any"

    def on_start(self):
        self.fast_n = int(self.p("fast", 12))
        self.slow_n = int(self.p("slow", 26))
        self.sig_n = int(self.p("signal", 9))
        self.pivot_n = int(self.p("pivot", 3))
        self.lookback = int(self.p("lookback", 60))
        self.k_f = 2 / (self.fast_n + 1)
        self.k_s = 2 / (self.slow_n + 1)
        self.k_sig = 2 / (self.sig_n + 1)
        self._ema_f = None
        self._ema_s = None
        self._ema_sig = None
        self._hist = None
        self._prev_hist = None
        self._warm = 0
        self._buf = deque(maxlen=self.pivot_n * 2 + 2)
        self._i = 0
        self._last_low_pivots = []
        self._last_high_pivots = []
        self._armed_bull = False
        self._armed_bear = False
        self._last_reason = ""

    def _detect_pivot(self):
        n = self.pivot_n
        mid = len(self._buf) - n - 1
        if mid < n:
            return
        c = self._buf[mid]
        is_low = True
        is_high = True
        for k in range(1, n + 1):
            l = self._buf[mid - k]
            r = self._buf[mid + k]
            if not (c["low"] < l["low"] and c["low"] < r["low"]):
                is_low = False
            if not (c["high"] > l["high"] and c["high"] > r["high"]):
                is_high = False
        if is_low:
            self._last_low_pivots.append({"i": c["i"], "price": c["low"], "hist": c["hist"]})
            if len(self._last_low_pivots) > 2:
                self._last_low_pivots.pop(0)
        if is_high:
            self._last_high_pivots.append({"i": c["i"], "price": c["high"], "hist": c["hist"]})
            if len(self._last_high_pivots) > 2:
                self._last_high_pivots.pop(0)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self._i += 1
        px = bar.close
        if self._ema_f is None:
            self._ema_f = px
        else:
            self._ema_f = (px - self._ema_f) * self.k_f + self._ema_f
        if self._ema_s is None:
            self._ema_s = px
        else:
            self._ema_s = (px - self._ema_s) * self.k_s + self._ema_s
        macd = self._ema_f - self._ema_s
        if self._ema_sig is None:
            self._ema_sig = macd
        else:
            self._ema_sig = (macd - self._ema_sig) * self.k_sig + self._ema_sig
        hist = macd - self._ema_sig
        self._warm += 1
        self._prev_hist = self._hist
        self._hist = hist

        if self._warm < self.slow_n + self.sig_n:
            return Signal.HOLD

        self._buf.append({"i": self._i, "low": bar.low, "high": bar.high, "hist": hist})
        self._detect_pivot()

        # Arm on divergence
        if len(self._last_low_pivots) == 2:
            a, b = self._last_low_pivots
            if (
                b["i"] - a["i"] <= self.lookback
                and b["price"] < a["price"]
                and b["hist"] > a["hist"]
                and b["hist"] < 0
            ):
                self._armed_bull = True
                self._last_reason = (
                    f"bull div price {a['price']:.4f}->{b['price']:.4f}, "
                    f"hist {a['hist']:.4f}->{b['hist']:.4f}"
                )
        if len(self._last_high_pivots) == 2:
            a, b = self._last_high_pivots
            if (
                b["i"] - a["i"] <= self.lookback
                and b["price"] > a["price"]
                and b["hist"] < a["hist"]
                and b["hist"] > 0
            ):
                self._armed_bear = True
                self._last_reason = (
                    f"bear div price {a['price']:.4f}->{b['price']:.4f}, "
                    f"hist {a['hist']:.4f}->{b['hist']:.4f}"
                )

        # Fire on histogram zero cross once armed
        if self._prev_hist is not None:
            if self._armed_bull and self._prev_hist <= 0 and hist > 0:
                self._armed_bull = False
                self._last_low_pivots = []
                return Signal.BUY
            if self._armed_bear and self._prev_hist >= 0 and hist < 0:
                self._armed_bear = False
                self._last_high_pivots = []
                return Signal.SELL

        return Signal.HOLD

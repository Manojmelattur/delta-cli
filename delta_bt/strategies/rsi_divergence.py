"""RSI divergence strategy.

Params: rsi_len(14), pivot(3), lookback(60), exit_mid(50),
        rsi_os(30), rsi_ob(70)
Bullish: price lower low + RSI higher low (RSI oversold) -> BUY.
Bearish: price higher high + RSI lower high (RSI overbought) -> SELL.
Exit when RSI crosses back through the midline.
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal, Side


class RsiDivergence(Strategy):
    name = "rsi_divergence"
    regime = "any"

    def on_start(self):
        self.rsi_len = int(self.p("rsi_len", 14))
        self.pivot_n = int(self.p("pivot", 3))
        self.lookback = int(self.p("lookback", 60))
        self.exit_mid = float(self.p("exit_mid", 50))
        self.rsi_os = float(self.p("rsi_os", 30))   # oversold threshold
        self.rsi_ob = float(self.p("rsi_ob", 70))   # overbought threshold
        self._init_state()

    def _init_state(self):
        self._prev_close: float | None = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._warm = 0
        self._rsi: float | None = None
        # pivot_n * 2 + 1: centre at index pivot_n, right wing ends at pivot_n * 2
        self._hist: deque[dict] = deque(maxlen=self.pivot_n * 2 + 1)
        self._i = 0
        self._last_low_pivots: deque[dict] = deque(maxlen=2)
        self._last_high_pivots: deque[dict] = deque(maxlen=2)
        self._last_reason = ""
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _update_rsi(self, px: float):
        if self._prev_close is None:
            self._prev_close = px
            return
        ch = px - self._prev_close
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        self._warm += 1
        if self._warm <= self.rsi_len:
            self._avg_gain += gain / self.rsi_len
            self._avg_loss += loss / self.rsi_len
        else:
            self._avg_gain = (self._avg_gain * (self.rsi_len - 1) + gain) / self.rsi_len
            self._avg_loss = (self._avg_loss * (self.rsi_len - 1) + loss) / self.rsi_len
        self._prev_close = px
        if self._warm < self.rsi_len:
            return
        if self._avg_loss == 0:
            self._rsi = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self._rsi = 100 - 100 / (1 + rs)

    def _detect_pivot(self):
        n = self.pivot_n
        # Buffer is maxlen = 2n+1; centre is always at index n once full.
        if len(self._hist) < self.pivot_n * 2 + 1:
            return
        mid = n
        c = self._hist[mid]
        is_low = True
        is_high = True
        for k in range(1, n + 1):
            l = self._hist[mid - k]
            r = self._hist[mid + k]
            if not (c["low"] < l["low"] and c["low"] < r["low"]):
                is_low = False
            if not (c["high"] > l["high"] and c["high"] > r["high"]):
                is_high = False
        if is_low:
            self._last_low_pivots.append(
                {"i": c["i"], "price": c["low"], "rsi": c["rsi"]}
            )
        if is_high:
            self._last_high_pivots.append(
                {"i": c["i"], "price": c["high"], "rsi": c["rsi"]}
            )

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self._i += 1
        self._update_rsi(bar.close)
        if self._rsi is None:
            return Signal.HOLD

        self._hist.append(
            {"i": self._i, "low": bar.low, "high": bar.high, "rsi": self._rsi}
        )
        self._detect_pivot()

        in_long = ctx.position.is_open and ctx.position.side == Side.LONG
        in_short = ctx.position.is_open and ctx.position.side == Side.SHORT

        # Exit when RSI crosses back through the midline.
        # Long entered on oversold RSI — exit when RSI drops back to/below mid.
        if in_long and self._rsi <= self.exit_mid:
            self._state = 0
            self._last_reason = f"long exit rsi {self._rsi:.2f} <= {self.exit_mid}"
            return Signal.FLAT
        # Short entered on overbought RSI — exit when RSI rises back to/above mid.
        if in_short and self._rsi >= self.exit_mid:
            self._state = 0
            self._last_reason = f"short exit rsi {self._rsi:.2f} >= {self.exit_mid}"
            return Signal.FLAT

        if ctx.position.is_open:
            return Signal.HOLD

        # Bullish divergence: price lower low, RSI higher low, RSI was oversold.
        if len(self._last_low_pivots) == 2:
            a, b = self._last_low_pivots
            if (
                b["i"] - a["i"] <= self.lookback
                and b["price"] < a["price"]
                and b["rsi"] > a["rsi"]
                and b["rsi"] < self.rsi_os
            ):
                self._state = 1
                self._last_low_pivots.clear()
                self._last_reason = (
                    f"bull div price {a['price']:.4f}->{b['price']:.4f}, "
                    f"rsi {a['rsi']:.2f}->{b['rsi']:.2f}"
                )
                return Signal.BUY

        # Bearish divergence: price higher high, RSI lower high, RSI was overbought.
        if len(self._last_high_pivots) == 2:
            a, b = self._last_high_pivots
            if (
                b["i"] - a["i"] <= self.lookback
                and b["price"] > a["price"]
                and b["rsi"] < a["rsi"]
                and b["rsi"] > self.rsi_ob
            ):
                self._state = -1
                self._last_high_pivots.clear()
                self._last_reason = (
                    f"bear div price {a['price']:.4f}->{b['price']:.4f}, "
                    f"rsi {a['rsi']:.2f}->{b['rsi']:.2f}"
                )
                return Signal.SELL

        self._last_reason = ""
        return Signal.HOLD

    def intent(self) -> Signal:
        if self._state == 1:
            return Signal.BUY
        if self._state == -1:
            return Signal.SELL
        return Signal.HOLD

    def on_stop(self):
        self._init_state()

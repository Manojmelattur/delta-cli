"""
Ichimoku Kinko Hyo Cloud Breakout Strategy.

Trades Kumo Cloud breakouts when Tenkan-sen crosses Kijun-sen
above/below the Cloud (Senkou Span A & B).

Params:
    tenkan_period   (int, default 9)  — Conversion line period
    kijun_period    (int, default 26) — Base line period
    senkou_b_period (int, default 52) — Leading Span B period
"""
from __future__ import annotations

from collections import deque
from typing import List

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext


class IchimokuCloudStrategy(Strategy):
    name = "ichimoku_cloud"
    regime = "trend"

    def on_start(self):
        self.tenkan_period = int(self.p("tenkan_period", 9))
        self.kijun_period = int(self.p("kijun_period", 26))
        self.senkou_b_period = int(self.p("senkou_b_period", 52))
        self._init_state()

    def _init_state(self):
        self._bars: deque[Bar] = deque(maxlen=self.senkou_b_period)
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _hl_mid(self, bars_slice: List[Bar]) -> float:
        h = max(b.high for b in bars_slice)
        lo = min(b.low for b in bars_slice)
        return (h + lo) / 2.0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._bars.append(bar)

        # Wait for a full senkou_b_period window before producing signals.
        if len(self._bars) < self.senkou_b_period:
            return Signal.HOLD

        tenkan = self._hl_mid(list(self._bars)[-self.tenkan_period:])
        kijun = self._hl_mid(list(self._bars)[-self.kijun_period:])

        # Senkou Span A & B (Cloud boundaries)
        senkou_a = (tenkan + kijun) / 2.0
        senkou_b = self._hl_mid(list(self._bars))

        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)

        # Bullish TK Cross above Cloud (only if not already long).
        if tenkan > kijun and bar.close > cloud_top and self._state != 1:
            self._state = 1
            return Signal.BUY
        # Bearish TK Cross below Cloud (only if not already short).
        elif tenkan < kijun and bar.close < cloud_bottom and self._state != -1:
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

from __future__ import annotations

from typing import Any, Dict, List, Optional

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext


class IchimokuCloudStrategy(Strategy):
    """
    Ichimoku Kinko Hyo Cloud Breakout Strategy.

    Trades Kumo Cloud breakouts when Tenkan-sen crosses Kijun-sen
    above/below the Cloud (Senkou Span A & B).

    Params:
        tenkan_period   (int, default 9)  — Conversion line period
        kijun_period    (int, default 26) — Base line period
        senkou_b_period (int, default 52) — Leading Span B period
    """

    name = "ichimoku_cloud"
    regime = "trend"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self._bars: List[Bar] = []

    def _hl_mid(self, bars_slice: List[Bar]) -> float:
        h = max(b.high for b in bars_slice)
        lo = min(b.low for b in bars_slice)
        return (h + lo) / 2.0

    def on_bar(self, bar: Bar, ctx: Optional[StrategyContext] = None) -> Signal:
        self._bars.append(bar)
        t = int(self.p("tenkan_period", 9))
        k = int(self.p("kijun_period", 26))
        sb = int(self.p("senkou_b_period", 52))
        if len(self._bars) < sb:
            return Signal.HOLD

        tenkan = self._hl_mid(self._bars[-t:])
        kijun = self._hl_mid(self._bars[-k:])

        # Senkou Span A & B (Cloud boundaries)
        senkou_a = (tenkan + kijun) / 2.0
        senkou_b = self._hl_mid(self._bars[-sb:])

        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)

        # Bullish TK Cross above Cloud
        if tenkan > kijun and bar.close > cloud_top:
            return Signal.BUY
        # Bearish TK Cross below Cloud
        elif tenkan < kijun and bar.close < cloud_bottom:
            return Signal.SELL

        return Signal.HOLD

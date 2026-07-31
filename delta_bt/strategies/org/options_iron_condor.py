from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext


class OptionsIronCondorStrategy(Strategy):
    """
    Automated 0DTE Options Iron Condor Strategy.

    Sells OTM Call & Put Credit Spreads on daily expiry options when the
    underlying is in a low-volatility range (inside Bollinger Bands).
    Signals SELL (enter condor credit) when range-bound, HOLD otherwise.

    Params:
        bb_period    (int,   default 20)   — Bollinger Band lookback
        bb_std       (float, default 2.0)  — Bollinger Band std multiplier
        delta_target (float, default 0.15) — Target delta for short strikes
    """

    name = "options_iron_condor"
    regime = "range"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self._bars: List[Bar] = []

    def on_bar(self, bar: Bar, ctx: Optional[StrategyContext] = None) -> Signal:
        self._bars.append(bar)
        period = int(self.p("bb_period", 20))
        if len(self._bars) < period:
            return Signal.HOLD

        bb_std = float(self.p("bb_std", 2.0))
        closes = [b.close for b in self._bars[-period:]]
        sma = sum(closes) / float(period)
        variance = sum((x - sma) ** 2 for x in closes) / float(period)
        std_dev = math.sqrt(variance)

        upper_band = sma + bb_std * std_dev
        lower_band = sma - bb_std * std_dev

        # Range-bound: sell Iron Condor when price comfortably inside bands
        if lower_band < bar.close < upper_band:
            return Signal.SELL  # short-vol credit position

        return Signal.HOLD

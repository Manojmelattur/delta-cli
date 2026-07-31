from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.options import move_contract_fair_value


class MoveVolatilityStraddleStrategy(Strategy):
    """
    MOVE (MV) Contract Volatility Strategy.

    Buys MOVE contracts before high-volatility regime expansions (ATR expanding)
    and sells MOVE contracts during low-volatility consolidation (theta decay capture).

    Params:
        atr_period  (int,   default 14)    — ATR lookback
        iv_annual   (float, default 0.65)  — Implied volatility estimate (annualised)
        mode        (str,   default long_vol) — 'long_vol' (Buy MOVE) or 'short_vol' (Sell MOVE)
    """

    name = "move_volatility_straddle"
    regime = "any"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        self._bars: List[Bar] = []

    def on_bar(self, bar: Bar, ctx: Optional[StrategyContext] = None) -> Signal:
        self._bars.append(bar)
        period = int(self.p("atr_period", 14))
        if len(self._bars) < period + 1:
            return Signal.HOLD

        iv = float(self.p("iv_annual", 0.65))
        mode = str(self.p("mode", "long_vol"))

        # Calculate ATR
        tr_list = []
        for i in range(len(self._bars) - period, len(self._bars)):
            b = self._bars[i]
            prev_b = self._bars[i - 1]
            tr = max(b.high - b.low, abs(b.high - prev_b.close), abs(b.low - prev_b.close))
            tr_list.append(tr)

        current_atr = tr_list[-1]
        avg_atr = sum(tr_list) / float(period)

        move_contract_fair_value(bar.close, 1.0, iv)  # validate options module available

        if mode == "long_vol":
            # Volatility expansion → Buy MOVE
            if current_atr > avg_atr * 1.3:
                return Signal.BUY
        else:
            # Volatility contraction → Sell MOVE for theta decay
            if current_atr < avg_atr * 0.8:
                return Signal.SELL

        return Signal.HOLD

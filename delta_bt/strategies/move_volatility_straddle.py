"""
MOVE (MV) Contract Volatility Strategy.

Buys MOVE contracts before high-volatility regime expansions (ATR expanding)
and sells MOVE contracts during low-volatility consolidation (theta decay capture).

Params:
    atr_period  (int,   default 14)       — ATR lookback
    iv_annual   (float, default 0.65)     — Implied volatility estimate (annualised)
    mode        (str,   default long_vol) — 'long_vol' (Buy MOVE) or 'short_vol' (Sell MOVE)
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.types import Bar, Signal
from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.options import move_contract_fair_value


class MoveVolatilityStraddleStrategy(Strategy):
    name = "move_volatility_straddle"
    regime = "any"

    def on_start(self):
        self.atr_period = int(self.p("atr_period", 14))
        self.iv_annual = float(self.p("iv_annual", 0.65))
        self.mode = str(self.p("mode", "long_vol"))
        if self.mode not in ("long_vol", "short_vol"):
            raise ValueError(
                f"Invalid mode '{self.mode}': must be 'long_vol' or 'short_vol'."
            )
        self._init_state()

    def _init_state(self):
        self._bars: deque[Bar] = deque(maxlen=self.atr_period + 1)
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _calc_atr(self) -> tuple[float, float]:
        """Return (current_tr, avg_atr) over the full window."""
        bars = list(self._bars)
        tr_list = []
        for i in range(1, self.atr_period + 1):
            b, prev = bars[i], bars[i - 1]
            tr = max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close))
            tr_list.append(tr)
        return tr_list[-1], sum(tr_list) / self.atr_period

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._bars.append(bar)

        if len(self._bars) < self.atr_period + 1:
            return Signal.HOLD

        current_atr, avg_atr = self._calc_atr()

        # Use fair value to confirm the contract is reasonably priced before trading.
        fair_value = move_contract_fair_value(bar.close, 1.0, self.iv_annual)
        fv = fair_value.get("fair_value") if fair_value else None
        if fv is None or fv <= 0:
            return Signal.HOLD

        if self.mode == "long_vol":
            # Volatility expansion → Buy MOVE (only if not already long).
            if current_atr > avg_atr * 1.3 and self._state != 1:
                self._state = 1
                return Signal.BUY
        else:
            # Volatility contraction → Sell MOVE for theta decay (only if not already short).
            if current_atr < avg_atr * 0.8 and self._state != -1:
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

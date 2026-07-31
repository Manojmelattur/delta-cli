"""VWAP Standard Deviation Bands Strategy.

Combines daily VWAP with rolling standard deviation bands and an RSI filter.
Buy when price hits lower band (oversold), Sell when price hits upper band (overbought).

Params:
- mult (float): standard deviation multiplier (default 2.0)
- stdev_len (int): rolling window for standard deviation (default 50)
- rsi_len (int): RSI length (default 14)
- rsi_buy_max (float): Max RSI to allow buys (default 40)
- rsi_sell_min (float): Min RSI to allow sells (default 60)
"""
from __future__ import annotations

import math
from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class VwapBands(Strategy):
    name = "vwap_bands"
    regime = "ranging"

    def on_start(self):
        self.mult = float(self.p("mult", 2.0))
        self.stdev_len = int(self.p("stdev_len", 50))
        self.rsi_len = int(self.p("rsi_len", 14))
        self.rsi_buy_max = float(self.p("rsi_buy_max", 45.0))
        self.rsi_sell_min = float(self.p("rsi_sell_min", 55.0))
        self._init_state()

    def _init_state(self):
        self._day = None
        self._pv = 0.0
        self._v = 0.0
        self._closes: deque[float] = deque(maxlen=self.stdev_len)
        # Wilder's RSI accumulators
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._rsi_warm = 0
        self._prev_close: float | None = None
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _update_rsi(self, close: float):
        if self._prev_close is None:
            return
        change = close - self._prev_close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self._rsi_warm += 1
        if self._rsi_warm <= self.rsi_len:
            # Seed phase: accumulate simple average.
            self._avg_gain += gain / self.rsi_len
            self._avg_loss += loss / self.rsi_len
        else:
            # Wilder's smoothing.
            self._avg_gain = (self._avg_gain * (self.rsi_len - 1) + gain) / self.rsi_len
            self._avg_loss = (self._avg_loss * (self.rsi_len - 1) + loss) / self.rsi_len

    def _calc_rsi(self) -> float:
        if self._rsi_warm < self.rsi_len:
            return 50.0
        al = self._avg_loss if self._avg_loss > 0 else 1e-9
        return 100.0 - (100.0 / (1.0 + self._avg_gain / al))

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        d = bar.ts.date()
        if d != self._day:
            self._day = d
            self._pv = 0.0
            self._v = 0.0

        typical = (bar.high + bar.low + bar.close) / 3.0
        vol = bar.volume if bar.volume > 0 else 1.0
        self._pv += typical * vol
        self._v += vol
        vwap = self._pv / self._v if self._v > 0 else bar.close

        self._closes.append(bar.close)
        self._update_rsi(bar.close)

        pc = self._prev_close
        self._prev_close = bar.close

        if len(self._closes) < self.stdev_len or pc is None:
            return Signal.HOLD

        # Standard deviation bands around VWAP.
        mean = sum(self._closes) / len(self._closes)
        variance = sum((x - mean) ** 2 for x in self._closes) / len(self._closes)
        std = math.sqrt(variance)
        upper = vwap + self.mult * std
        lower = vwap - self.mult * std

        pu = self._prev_upper
        pl = self._prev_lower
        self._prev_upper = upper
        self._prev_lower = lower

        if pu is None or pl is None:
            return Signal.HOLD

        rsi = self._calc_rsi()
        c = bar.close

        # Edge triggers for mean reversion:
        # Buy when price crosses below lower band and RSI is low.
        crossed_down_lower = pc >= pl and c < lower
        # Sell when price crosses above upper band and RSI is high.
        crossed_up_upper = pc <= pu and c > upper

        if crossed_down_lower and rsi <= self.rsi_buy_max and self._state != 1:
            self._state = 1
            return Signal.BUY

        if crossed_up_upper and rsi >= self.rsi_sell_min and self._state != -1:
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

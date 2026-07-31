"""Stochastic RSI strategy.

Applies the Stochastic oscillator to RSI values to produce a
faster, more sensitive oscillator suited to ranging markets.

Params:
    rsi_len     (int,   default 14)  — RSI period
    stoch_len   (int,   default 14)  — Stochastic lookback over RSI values
    smooth_k    (int,   default 3)   — %K smoothing period
    smooth_d    (int,   default 3)   — %D smoothing period (signal line)
    os          (float, default 20)  — Oversold threshold
    ob          (float, default 80)  — Overbought threshold
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class StochasticRsi(Strategy):
    name = "stochastic_rsi"
    regime = "range"

    def on_start(self):
        self.rsi_len = int(self.p("rsi_len", 14))
        self.stoch_len = int(self.p("stoch_len", 14))
        self.smooth_k = int(self.p("smooth_k", 3))
        self.smooth_d = int(self.p("smooth_d", 3))
        self.os = float(self.p("os", 20.0))
        self.ob = float(self.p("ob", 80.0))
        self._init_state()

    def _init_state(self):
        # RSI accumulators (Wilder's smoothing)
        self._prev_close: float | None = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._rsi_warm = 0
        self._rsi: float | None = None
        # Stochastic RSI buffers
        self._rsi_buf: deque[float] = deque(maxlen=self.stoch_len)
        self._k_buf: deque[float] = deque(maxlen=self.smooth_k)
        self._d_buf: deque[float] = deque(maxlen=self.smooth_d)
        self._prev_k: float | None = None
        self._prev_d: float | None = None
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def _update_rsi(self, close: float):
        if self._prev_close is None:
            self._prev_close = close
            return
        change = close - self._prev_close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self._rsi_warm += 1
        if self._rsi_warm <= self.rsi_len:
            self._avg_gain += gain / self.rsi_len
            self._avg_loss += loss / self.rsi_len
        else:
            self._avg_gain = (self._avg_gain * (self.rsi_len - 1) + gain) / self.rsi_len
            self._avg_loss = (self._avg_loss * (self.rsi_len - 1) + loss) / self.rsi_len
        self._prev_close = close
        if self._rsi_warm < self.rsi_len:
            return
        al = self._avg_loss if self._avg_loss > 0 else 1e-9
        self._rsi = 100.0 - 100.0 / (1.0 + self._avg_gain / al)

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._update_rsi(bar.close)
        if self._rsi is None:
            return Signal.HOLD

        self._rsi_buf.append(self._rsi)
        if len(self._rsi_buf) < self.stoch_len:
            return Signal.HOLD

        # Raw Stochastic RSI (%K before smoothing)
        lo = min(self._rsi_buf)
        hi = max(self._rsi_buf)
        rng = hi - lo
        raw_k = (self._rsi - lo) / rng * 100.0 if rng > 0 else 50.0

        # Smooth %K
        self._k_buf.append(raw_k)
        if len(self._k_buf) < self.smooth_k:
            return Signal.HOLD
        k = sum(self._k_buf) / self.smooth_k

        # Smooth %D (signal line)
        self._d_buf.append(k)
        if len(self._d_buf) < self.smooth_d:
            self._prev_k = k
            return Signal.HOLD
        d = sum(self._d_buf) / self.smooth_d

        prev_k = self._prev_k
        prev_d = self._prev_d
        self._prev_k = k
        self._prev_d = d

        if prev_k is None or prev_d is None:
            return Signal.HOLD

        # BUY: %K crosses above %D from below oversold threshold.
        if prev_k <= prev_d and k > d and k < self.os and self._state != 1:
            self._state = 1
            return Signal.BUY

        # SELL: %K crosses below %D from above overbought threshold.
        if prev_k >= prev_d and k < d and k > self.ob and self._state != -1:
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

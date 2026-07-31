"""On-Balance Volume (OBV) trend strategy.

OBV accumulates volume directionally: adds volume on up-bars,
subtracts on down-bars. Trend is determined by an EMA of OBV.
Enters when OBV crosses above/below its EMA and price confirms
by being above/below its own EMA.

Params:
    obv_ema_len  (int, default 20)  — EMA period applied to OBV
    price_ema_len (int, default 50) — Price EMA for trend confirmation
"""
from __future__ import annotations

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class ObvTrend(Strategy):
    name = "obv_trend"
    regime = "trend"

    def on_start(self):
        self.obv_ema_len = int(self.p("obv_ema_len", 20))
        self.price_ema_len = int(self.p("price_ema_len", 50))
        self._init_state()

    def _init_state(self):
        self._prev_close: float | None = None
        self._obv = 0.0
        self._obv_ema: float | None = None
        self._price_ema: float | None = None
        self._prev_obv_above: bool | None = None  # was OBV above its EMA last bar
        self._k_obv = 2 / (self.obv_ema_len + 1)
        self._k_price = 2 / (self.price_ema_len + 1)
        self._warm = 0
        self._state = 0  # 1 = long, -1 = short, 0 = flat

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Reset self-latch when flat so re-entry after external SL/TSL exits works.
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        c = bar.close
        vol = bar.volume if bar.volume > 0 else 0.0

        # --- OBV accumulation ---
        if self._prev_close is not None:
            if c > self._prev_close:
                self._obv += vol
            elif c < self._prev_close:
                self._obv -= vol
            # unchanged close: OBV unchanged
        self._prev_close = c

        # --- EMA updates ---
        self._obv_ema = (
            self._obv if self._obv_ema is None
            else (self._obv - self._obv_ema) * self._k_obv + self._obv_ema
        )
        self._price_ema = (
            c if self._price_ema is None
            else (c - self._price_ema) * self._k_price + self._price_ema
        )

        self._warm += 1
        if self._warm < max(self.obv_ema_len, self.price_ema_len):
            return Signal.HOLD

        obv_ema = self._obv_ema
        price_ema = self._price_ema
        if obv_ema is None or price_ema is None:
            return Signal.HOLD

        obv_above = self._obv > obv_ema
        prev_obv_above = self._prev_obv_above
        self._prev_obv_above = obv_above

        if prev_obv_above is None:
            return Signal.HOLD

        # --- Entries: OBV crosses EMA, confirmed by price vs price EMA ---
        # Bullish: OBV crosses above its EMA and price is above price EMA.
        if not prev_obv_above and obv_above and c > price_ema and self._state != 1:
            self._state = 1
            return Signal.BUY

        # Bearish: OBV crosses below its EMA and price is below price EMA.
        if prev_obv_above and not obv_above and c < price_ema and self._state != -1:
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

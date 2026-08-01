"""Strategy: Time Session Breakout.

Triggers trades when the intraday price breaks above the previous session's high,
or breaks below the previous session's low.

Params:
    period (str, default 'day') - The session to track ('day', 'hour', '4h')
    use_volume_filter (bool, default False) - Require volume to be higher than average
    vol_lookback (int, default 10) - Lookback for volume average
    vol_mult (float, default 1.2) - Multiplier for volume average
"""
from __future__ import annotations

from collections import deque
import datetime

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class TimeBreakout(Strategy):
    name = "time_breakout"
    regime = "trend"

    def on_start(self):
        self.period = str(self.p("period", "day")).lower()
        self.use_volume_filter = str(self.p("use_volume_filter", "false")).lower() == "true"
        self.vol_lookback = int(self.p("vol_lookback", 10))
        self.vol_mult = float(self.p("vol_mult", 1.2))
        self._init_state()

    def _init_state(self):
        self._state = 0  # 1 = long, -1 = short, 0 = flat
        self._current_period_id = None
        self._curr_period_high = 0.0
        self._curr_period_low = float('inf')
        self._prev_period_high: float | None = None
        self._prev_period_low: float | None = None
        self._vols: deque[float] = deque(maxlen=self.vol_lookback)

    def _get_period_id(self, ts: datetime.datetime):
        if self.period == "hour":
            return ts.replace(minute=0, second=0, microsecond=0)
        elif self.period == "4h":
            return ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0)
        # default to day
        return ts.date()

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        if getattr(ctx.position, "qty", 0) == 0 and self._state != 0:
            self._state = 0

        self._vols.append(bar.volume)
        period_id = self._get_period_id(bar.ts)

        # Period transition logic
        if self._current_period_id is None:
            self._current_period_id = period_id
            self._curr_period_high = bar.high
            self._curr_period_low = bar.low
        elif period_id != self._current_period_id:
            # Shift current period tracking to previous period
            self._prev_period_high = self._curr_period_high
            self._prev_period_low = self._curr_period_low
            
            # Reset current period tracking for the new period
            self._current_period_id = period_id
            self._curr_period_high = bar.high
            self._curr_period_low = bar.low
        else:
            # Update current period tracking
            self._curr_period_high = max(self._curr_period_high, bar.high)
            self._curr_period_low = min(self._curr_period_low, bar.low)

        # Wait until we have a previous period's high/low to compare against
        if self._prev_period_high is None or self._prev_period_low is None:
            return Signal.HOLD

        # Optional volume confirmation
        volume_confirmed = True
        if self.use_volume_filter and len(self._vols) == self.vol_lookback:
            prior_vols = list(self._vols)[:-1]
            if prior_vols:
                avg_vol = sum(prior_vols) / len(prior_vols)
                volume_confirmed = bar.volume > avg_vol * self.vol_mult

        # Breakout checks
        if bar.close > self._prev_period_high and volume_confirmed and self._state != 1:
            self._state = 1
            return Signal.BUY
            
        elif bar.close < self._prev_period_low and volume_confirmed and self._state != -1:
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

"""Classic Turtle Trading (Donchian channel breakout).

Params: entry_len(20), exit_len(10), allow_short(true)
Entry: close breaks above N-bar high (long) / below N-bar low (short).
Exit: close crosses opposing M-bar channel.
"""
from __future__ import annotations

from collections import deque

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal, Side


class Turtle(Strategy):
    name = "turtle"

    regime = "trend"

    def on_start(self):
        self.entry_len = int(self.p("entry_len", 20))
        self.exit_len = int(self.p("exit_len", 10))
        self.allow_short = bool(self.p("allow_short", True))
        cap = max(self.entry_len, self.exit_len) + 2
        self._highs = deque(maxlen=cap)
        self._lows = deque(maxlen=cap)
        self._last_reason = ""

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Channels computed from PRIOR bars (exclude current bar to avoid look-ahead).
        highs = list(self._highs)
        lows = list(self._lows)
        entry_high = max(highs[-self.entry_len:]) if len(highs) >= self.entry_len else None
        entry_low = min(lows[-self.entry_len:]) if len(lows) >= self.entry_len else None
        exit_high = max(highs[-self.exit_len:]) if len(highs) >= self.exit_len else None
        exit_low = min(lows[-self.exit_len:]) if len(lows) >= self.exit_len else None

        c = bar.close
        in_long = ctx.position.is_open and ctx.position.side == Side.LONG
        in_short = ctx.position.is_open and ctx.position.side == Side.SHORT

        # Exits
        if in_long and exit_low is not None and c < exit_low:
            self._last_reason = f"long exit {c:.4f} < {self.exit_len}-low {exit_low:.4f}"
            self._highs.append(bar.high)
            self._lows.append(bar.low)
            return Signal.FLAT
        if in_short and exit_high is not None and c > exit_high:
            self._last_reason = f"short exit {c:.4f} > {self.exit_len}-high {exit_high:.4f}"
            self._highs.append(bar.high)
            self._lows.append(bar.low)
            return Signal.FLAT

        if ctx.position.is_open:
            self._highs.append(bar.high)
            self._lows.append(bar.low)
            return Signal.HOLD

        # Entries
        if entry_high is not None and c > entry_high:
            self._last_reason = f"bull breakout {c:.4f} > {self.entry_len}-high {entry_high:.4f}"
            self._highs.append(bar.high)
            self._lows.append(bar.low)
            return Signal.BUY
        if self.allow_short and entry_low is not None and c < entry_low:
            self._last_reason = f"bear breakout {c:.4f} < {self.entry_len}-low {entry_low:.4f}"
            self._highs.append(bar.high)
            self._lows.append(bar.low)
            return Signal.SELL

        self._last_reason = ""
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        return Signal.HOLD

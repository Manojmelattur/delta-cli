"""Bollinger Bands strategy.

Params: period(20), stdev(2.0), mode("revert"|"breakout")
"""
from __future__ import annotations

from collections import deque
import math

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Bollinger(Strategy):
    name   = "bollinger"
    regime = "range"

    def on_start(self):
        self.n    = int(self.p("period", 20))
        self.k    = float(self.p("stdev", 2.0))
        self.mode = self.p("mode", "revert")
        self.w    = deque(maxlen=self.n)
        self._state  = 0   # 1=long, -1=short, 0=flat
        self._intent = 0   # 1=want long, -1=want short, 0=neutral

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _bands(self) -> tuple:
        """Return (mean, upper, lower) from current window.

        Fix 5: extracted from on_bar and intent to avoid duplication.
        Returns (None, None, None) if window is not full.
        """
        if len(self.w) < self.n:
            return None, None, None
        mean  = sum(self.w) / self.n
        var   = sum((x - mean) ** 2 for x in self.w) / self.n
        sd    = math.sqrt(var)
        return mean, mean + self.k * sd, mean - self.k * sd

    def _is_flat(self, ctx: StrategyContext) -> bool:
        """Fix 1: check position flatness using open_side not qty.

        Position is flat when open_side is None or empty string.
        qty does not exist on the Position dataclass used by the scheduler.
        """
        pos = ctx.position
        # Support both scheduler Position (has open_side) and
        # scanner Position (has qty as fallback)
        open_side = getattr(pos, "open_side", None)
        if open_side is not None:
            return not open_side
        # Fallback for scanner StrategyContext
        qty = getattr(pos, "qty", 0)
        return qty == 0

    # ------------------------------------------------------------------
    # Main signal logic
    # ------------------------------------------------------------------
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        # Fix 1: use _is_flat() instead of qty check
        if self._is_flat(ctx) and self._state != 0:
            self._state  = 0
            # Fix 2: also reset _intent when position is externally closed
            self._intent = 0

        self.w.append(bar.close)
        mean, upper, lower = self._bands()
        if mean is None:
            return Signal.HOLD

        c = bar.close

        if self.mode == "revert":
            # Update intent AFTER state checks to avoid same-bar conflicts
            # Fix 6: intent update moved to after signal emission checks

            # Exit signals — check before entry
            if self._state == 1 and c >= mean:
                self._state  = 0
                # Fix 2: reset _intent on FLAT so re-entry does not fire immediately
                self._intent = 0
                return Signal.FLAT
            if self._state == -1 and c <= mean:
                self._state  = 0
                self._intent = 0
                return Signal.FLAT

            # Entry signals
            if c < lower and self._state != 1:
                self._state  = 1
                self._intent = 1
                return Signal.BUY
            if c > upper and self._state != -1:
                self._state  = -1
                self._intent = -1
                return Signal.SELL

            # Update intent for intent() method
            if c < lower:
                self._intent = 1
            elif c > upper:
                self._intent = -1
            elif self._intent == 1 and c >= mean:
                self._intent = 0
            elif self._intent == -1 and c <= mean:
                self._intent = 0

        else:
            # Breakout mode
            # Fix 3: reset state when price returns inside bands
            # so the bot can re-enter on the next breakout
            if self._state == 1 and c < mean:
                self._state  = 0
                self._intent = 0
            elif self._state == -1 and c > mean:
                self._state  = 0
                self._intent = 0

            if c > upper and self._state != 1:
                self._state  = 1
                self._intent = 1
                return Signal.BUY
            if c < lower and self._state != -1:
                self._state  = -1
                self._intent = -1
                return Signal.SELL

        return Signal.HOLD

    def intent(self, bar: Bar) -> Signal:
        """Current desired position based on the last closed bar.

        Fix 4: intent() must NOT append bar.close to self.w since
        on_bar already did so. Bands are calculated from the existing
        window without re-adding the bar.

        Used by the scheduler when the signal fired outside the tail
        window but the setup is still valid.
        """
        # Fix 5: use shared _bands() helper
        mean, upper, lower = self._bands()
        if mean is None:
            return Signal.HOLD

        c = bar.close

        if self.mode == "revert":
            # Exit intent — position should close
            if self._state == 1  and c >= mean: return Signal.FLAT
            if self._state == -1 and c <= mean: return Signal.FLAT
            if self._intent == 1  and c >= mean: return Signal.FLAT
            if self._intent == -1 and c <= mean: return Signal.FLAT

            # Entry intent — position should open
            if self._state == 1  and c < mean:  return Signal.BUY
            if self._state == -1 and c > mean:  return Signal.SELL
            if self._intent == 1  and c < mean:  return Signal.BUY
            if self._intent == -1 and c > mean:  return Signal.SELL
            if c < lower: return Signal.BUY
            if c > upper: return Signal.SELL

        else:
            # Breakout intent
            if self._intent == 1  or self._state == 1:  return Signal.BUY
            if self._intent == -1 or self._state == -1: return Signal.SELL
            if c > upper: return Signal.BUY
            if c < lower: return Signal.SELL

        return Signal.HOLD

    def on_stop(self):
        """Reset state on strategy stop so backtest reruns start clean."""
        self._state  = 0
        self._intent = 0

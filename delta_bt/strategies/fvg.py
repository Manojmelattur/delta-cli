"""Fair Value Gap (FVG) strategy.

Detects 3-bar FVGs on the most recent closed candles:
  Bullish FVG : bar[0].low  > bar[2].high  AND bar[1] does not fill the gap
  Bearish FVG : bar[0].high < bar[2].low   AND bar[1] does not fill the gap

Enters in the direction of the last FVG when price retests the gap zone.

Params:
    lookback_close (int, default 50) : Bars a gap stays valid before expiring
"""
from __future__ import annotations

from collections import deque
from typing import Optional

from delta_bt.core.strategy import Strategy, StrategyContext
from delta_bt.core.types import Bar, Signal


class Fvg(Strategy):
    name   = "fvg"
    regime = "any"

    def __init__(self, params: Optional[dict] = None):
        super().__init__(params if params is not None else {})
        self._initialised = False

    def _init_state(self) -> None:
        """Initialise or reset all strategy state."""
        self.lookback       = int(self.p("lookback_close", 50))
        self.bars: deque[Bar] = deque(maxlen=3)
        # Each gap: [side, lo, hi, age]
        # Using dicts instead of lists to avoid value-based remove bugs
        self.gaps: list     = []
        self._state: int    = 0   # 1=long, -1=short, 0=flat
        self._initialised   = True

    def on_start(self) -> None:
        self._init_state()

    def _ensure_init(self) -> None:
        if not self._initialised:
            self._init_state()

    def _is_flat(self, ctx: StrategyContext) -> bool:
        """Fix 1: check flatness using open_side with qty fallback."""
        pos       = ctx.position
        open_side = getattr(pos, "open_side", None)
        if open_side is not None:
            return not open_side
        return getattr(pos, "qty", 0) == 0

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        self._ensure_init()

        # Fix 1: use _is_flat() instead of qty check
        if self._is_flat(ctx) and self._state != 0:
            self._state = 0

        self.bars.append(bar)

        # Detect new FVG using closed 3-bar window
        if len(self.bars) == 3:
            b2, b1, b0 = self.bars[0], self.bars[1], self.bars[2]

            # Fix 7: verify middle bar does not fill the gap
            if b0.low > b2.high and b1.high < b0.low and b1.low > b2.high:
                # Bullish FVG — gap between b2.high and b0.low
                self.gaps.append({
                    "side": "BUY",
                    "lo":   b2.high,
                    "hi":   b0.low,
                    "age":  0,
                })
            elif b0.high < b2.low and b1.low > b0.high and b1.high < b2.low:
                # Bearish FVG — gap between b0.high and b2.low
                self.gaps.append({
                    "side": "SELL",
                    "lo":   b0.high,
                    "hi":   b2.low,
                    "age":  0,
                })

        # Check retests — build new list to avoid mutation-during-iteration
        # Fix 2: use index-safe filtering instead of list.remove()
        # Fix 3: increment age after expiry check so gaps live exactly lookback bars
        surviving = []
        signal    = Signal.HOLD

        for g in self.gaps:
            # Fix 3: check expiry before incrementing age
            if g["age"] >= self.lookback:
                continue  # expired — drop without incrementing

            # Fix 4: check intrabar retest (high/low) not just close
            # price entered the gap zone if bar's range overlaps the gap
            retested = bar.low <= g["hi"] and bar.high >= g["lo"]

            if retested:
                # Gap consumed — do not add to surviving
                if signal == Signal.HOLD:
                    # Only fire the first retest signal per bar
                    if g["side"] == "BUY" and self._state != 1:
                        self._state = 1
                        signal      = Signal.BUY
                    elif g["side"] == "SELL" and self._state != -1:
                        self._state = -1
                        signal      = Signal.SELL
                continue

            # Gap still active — increment age and keep
            g["age"] += 1
            surviving.append(g)

        self.gaps = surviving
        return signal

    def intent(self, bar: Bar) -> Optional[Signal]:
        """Fix 5: return current intent based on active gaps.

        Returns BUY if there is an active bullish gap whose zone
        price is currently inside, SELL for bearish, HOLD otherwise.
        """
        self._ensure_init()

        for g in self.gaps:
            if g["age"] >= self.lookback:
                continue
            # Check if current bar is near or inside the gap zone
            if bar.low <= g["hi"] and bar.high >= g["lo"]:
                if g["side"] == "BUY":
                    return Signal.BUY
                if g["side"] == "SELL":
                    return Signal.SELL

        return Signal.HOLD

    def on_stop(self) -> None:
        """Fix 6: reset all state so backtest reruns start clean."""
        self._initialised = False

"""EMA crossover + RSI confirmation signal generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from utils.constants import SignalSide


@dataclass(frozen=True)
class Signal:
    """Trading signal with metadata."""

    side: SignalSide
    reason: str
    fast_ema: float
    slow_ema: float
    rsi: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side.value,
            "reason": self.reason,
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "rsi": self.rsi,
        }


def _crossover_above(prev_fast: float, prev_slow: float, fast: float, slow: float) -> bool:
    return prev_fast <= prev_slow and fast > slow


def _crossover_below(prev_fast: float, prev_slow: float, fast: float, slow: float) -> bool:
    return prev_fast >= prev_slow and fast < slow


def generate_signal(
    df: pd.DataFrame,
    rsi_buy_level: float,
    rsi_sell_level: float,
) -> Signal:
    """
    Evaluate the last two *closed* bars for crossover + RSI confirmation.

    Uses iloc[-3] and iloc[-2] so the forming bar (iloc[-1]) is excluded.
    """
    if len(df) < 4:
        return Signal(
            side=SignalSide.HOLD,
            reason="insufficient_data",
            fast_ema=0.0,
            slow_ema=0.0,
            rsi=0.0,
        )

    required = ("ema_fast", "ema_slow", "rsi")
    if any(col not in df.columns for col in required):
        return Signal(
            side=SignalSide.HOLD,
            reason="indicators_not_ready",
            fast_ema=0.0,
            slow_ema=0.0,
            rsi=0.0,
        )

    prev = df.iloc[-3]
    curr = df.iloc[-2]

    prev_fast = float(prev["ema_fast"])
    prev_slow = float(prev["ema_slow"])
    fast = float(curr["ema_fast"])
    slow = float(curr["ema_slow"])
    rsi = float(curr["rsi"])

    if pd.isna(fast) or pd.isna(slow) or pd.isna(rsi):
        return Signal(
            side=SignalSide.HOLD,
            reason="nan_indicators",
            fast_ema=fast,
            slow_ema=slow,
            rsi=rsi,
        )

    if _crossover_above(prev_fast, prev_slow, fast, slow) and rsi > rsi_buy_level:
        return Signal(
            side=SignalSide.BUY,
            reason="ema_cross_up_rsi_confirm",
            fast_ema=fast,
            slow_ema=slow,
            rsi=rsi,
        )

    if _crossover_below(prev_fast, prev_slow, fast, slow) and rsi < rsi_sell_level:
        return Signal(
            side=SignalSide.SELL,
            reason="ema_cross_down_rsi_confirm",
            fast_ema=fast,
            slow_ema=slow,
            rsi=rsi,
        )

    return Signal(
        side=SignalSide.HOLD,
        reason="no_signal",
        fast_ema=fast,
        slow_ema=slow,
        rsi=rsi,
    )


def opposite_crossover_signal(
    df: pd.DataFrame,
    current_side: str,
) -> bool:
    """True if EMA crossed opposite to the open position direction."""
    if len(df) < 4:
        return False

    prev = df.iloc[-3]
    curr = df.iloc[-2]
    prev_fast = float(prev["ema_fast"])
    prev_slow = float(prev["ema_slow"])
    fast = float(curr["ema_fast"])
    slow = float(curr["ema_slow"])

    if current_side == "long":
        return _crossover_below(prev_fast, prev_slow, fast, slow)
    if current_side == "short":
        return _crossover_above(prev_fast, prev_slow, fast, slow)
    return False

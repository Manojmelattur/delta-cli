"""Base Strategy class. Subclass this and drop in delta_bt/strategies/."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .types import Bar, Position, Signal


class StrategyContext:
    """Passed to strategy on each bar. Read-only view of engine state."""

    def __init__(
        self, 
        position: Position, 
        equity: float, 
        cash: float,
        funding_rate: Optional[float] = None,
        open_interest: Optional[float] = None,
    ):
        self.position = position
        self.equity = equity
        self.cash = cash
        self.funding_rate = funding_rate
        self.open_interest = open_interest


class Strategy:
    """Override `on_bar` (and optionally `on_start` / `on_stop`).

    Return a `Signal` from `on_bar`. Engine handles sizing / execution.
    """

    name: str = "base"
    # Regime tag used by the engine's optional ADX filter.
    #   "trend" → only fires when ADX >= trend_min
    #   "range" → only fires when ADX <  range_max
    #   "any"   → never vetoed (default)
    regime: str = "any"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = params or {}
        self.state: Dict[str, Any] = {}

    # ---- Lifecycle -------------------------------------------------------
    def on_start(self) -> None: ...
    def on_stop(self) -> None: ...

    # ---- Per-bar logic ---------------------------------------------------
    def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal:
        raise NotImplementedError

    def intent(self, bar: Bar) -> Optional[Signal]:
        return None

    # ---- Helpers ---------------------------------------------------------
    def p(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

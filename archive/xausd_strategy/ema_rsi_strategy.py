"""EMA + RSI strategy orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from core.config_loader import AppConfig
from core.risk_manager import RiskManager
from strategy.indicators import add_all_indicators
from strategy.signal_generator import Signal, generate_signal, opposite_crossover_signal
from utils.constants import ExitReason, PositionSide, SignalSide

if TYPE_CHECKING:
    from core.risk_manager import PositionState

logger = logging.getLogger("trading_bot.strategy")


class EmaRsiStrategy:
    """EMA crossover with RSI confirmation and exit evaluation."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._enabled = config.strategy.enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return dataframe with EMA and RSI columns."""
        return add_all_indicators(
            df,
            fast_ema=self._config.ema.fast_ema,
            slow_ema=self._config.ema.slow_ema,
            rsi_period=self._config.rsi.period,
        )

    def evaluate_entry(self, df: pd.DataFrame) -> Signal:
        """Generate entry signal from closed bars."""
        if not self._enabled:
            return Signal(
                side=SignalSide.HOLD,
                reason="strategy_disabled",
                fast_ema=0.0,
                slow_ema=0.0,
                rsi=0.0,
            )

        enriched = self.compute_indicators(df)
        return generate_signal(
            enriched,
            rsi_buy_level=self._config.rsi.buy_level,
            rsi_sell_level=self._config.rsi.sell_level,
        )

    def evaluate_exit(
        self,
        df: pd.DataFrame,
        position: PositionState,
        mark_price: float,
        risk_manager: object,
    ) -> ExitReason | None:
        """Check risk exits and opposite crossover."""
        enriched = self.compute_indicators(df)
        side_str = "long" if position.side == PositionSide.LONG else "short"
        opposite = opposite_crossover_signal(enriched, side_str)

        if not isinstance(risk_manager, RiskManager):
            raise TypeError("risk_manager must be RiskManager instance")

        return risk_manager.should_exit(
            position=position,
            mark_price=mark_price,
            opposite_crossover=opposite,
        )

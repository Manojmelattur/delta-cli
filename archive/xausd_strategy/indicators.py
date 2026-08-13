"""Technical indicators using pandas and ta library."""

from __future__ import annotations

import pandas as pd
import ta


def add_ema(df: pd.DataFrame, fast_period: int, slow_period: int) -> pd.DataFrame:
    """Add fast and slow EMA columns to dataframe."""
    result = df.copy()
    result["ema_fast"] = ta.trend.EMAIndicator(
        close=result["close"], window=fast_period
    ).ema_indicator()
    result["ema_slow"] = ta.trend.EMAIndicator(
        close=result["close"], window=slow_period
    ).ema_indicator()
    return result


def add_rsi(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Add RSI column to dataframe."""
    result = df.copy()
    result["rsi"] = ta.momentum.RSIIndicator(
        close=result["close"], window=period
    ).rsi()
    return result


def add_all_indicators(
    df: pd.DataFrame,
    fast_ema: int,
    slow_ema: int,
    rsi_period: int,
) -> pd.DataFrame:
    """Apply EMA and RSI indicators."""
    result = add_ema(df, fast_ema, slow_ema)
    return add_rsi(result, rsi_period)

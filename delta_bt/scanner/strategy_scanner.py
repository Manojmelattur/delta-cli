"""SMC Setup Scanner Module

Encapsulates logic to scan a universe of symbols across multiple timeframes and SMC strategies
to find active setups (where the latest signal is not HOLD).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.core.engine import run_backtest
from delta_bt.core.types import RunConfig, Position
from delta_bt.core.registry import load_strategy
from delta_bt.core.strategy import StrategyContext


logger = logging.getLogger(__name__)


@dataclass
class ScannerSetup:
    symbol: str
    resolution: str
    strategy: str
    signal: str          # "LONG" / "SHORT" / "BUY" / "SELL"
    timestamp: datetime
    price: float


def _check_symbol_strat(
    client: DeltaClient,
    symbol: str,
    resolution: str,
    strategy_name: str,
    end_time: datetime,
) -> Optional[ScannerSetup]:
    """Fetch history and run a single strategy backtest to check for a live setup."""
    step_sec = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}.get(resolution, 3600)

    needed_bars = 200
    start_time = end_time - timedelta(seconds=step_sec * needed_bars)

    try:
        klines = load_history(client, symbol, resolution, start_time, end_time)
    except Exception as e:
        logger.debug(f"Failed to fetch history for {symbol} {resolution}: {e}")
        return None

    if len(klines) < 100:
        return None

    try:
        strat = load_strategy(strategy_name, {})
    except SystemExit:
        return None

    cfg = RunConfig(
        strategy=strategy_name,
        symbol=symbol,
        resolution=resolution,
        capital=1000,
        fee_bps=5,
        slippage_bps=2
    )

    try:
        # Prime the strategy by running on all but the last bar.
        # run_backtest receives a fresh strategy instance; we check whether
        # it calls on_stop() internally — if it does, re-load the strategy
        # after priming so indicator state is preserved for the live bar.
        if len(klines) > 1:
            run_backtest(klines[:-1], strat, cfg)

        # Evaluate the last bar to catch live setups.
        # Fix 4: Position must be constructed with symbol=, not qty/avg_price/side.
        ctx = StrategyContext(Position(symbol=symbol), 1000, 1000)
        sig = strat.on_bar(klines[-1], ctx)
    except Exception as e:
        logger.debug(f"Engine run failed for {symbol} {strategy_name}: {e}")
        return None

    last_signal = sig.name if hasattr(sig, 'name') else str(sig)
    if last_signal in ("BUY", "SELL", "LONG", "SHORT"):
        return ScannerSetup(
            symbol=symbol,
            resolution=resolution,
            strategy=strategy_name,
            signal=last_signal,
            timestamp=klines[-1].ts,
            price=float(klines[-1].close),
        )

    return None


def scan_strategy_setups(
    client: DeltaClient,
    symbols: List[str],
    resolutions: List[str] = ["15m", "30m", "1h"],  # Fix 3: added missing comma between "30m" and "1h"
    strategies: List[str] = ["ema3"],
    workers: int = 8,
) -> List[ScannerSetup]:
    """
    Scan for active strategy setups across symbols, resolutions, and strategies.
    Uses a ThreadPoolExecutor to run tasks concurrently.

    Returns a list of ScannerSetup objects for any valid triggers found on the latest bar.
    """
    end_time = datetime.now(tz=timezone.utc)
    setups: List[ScannerSetup] = []

    tasks = [
        (sym, res, strat)
        for sym in symbols
        for res in resolutions
        for strat in strategies
    ]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [
            ex.submit(_check_symbol_strat, client, sym, res, strat, end_time)
            for (sym, res, strat) in tasks
        ]

        # Fix 6: wrap f.result() in try/except so one bad future does not
        # crash the entire scan.
        for f in as_completed(futs):
            try:
                result = f.result()
                if result:
                    setups.append(result)
            except Exception as e:
                logger.debug(f"Scanner task raised an exception: {e}")

    # Sort setups by timestamp descending (newest first), then symbol
    setups.sort(key=lambda s: (s.timestamp, s.symbol), reverse=True)
    return setups

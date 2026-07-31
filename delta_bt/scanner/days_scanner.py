"""SMC Setup Scanner Module

Encapsulates logic to scan a universe of symbols across multiple timeframes and SMC strategies
to find active setups (where the latest signal is not HOLD).

Profitability filter (30-day window):
  - Net PnL must be > 0
  - Win rate must be >= min_win_rate (default 50%)
  - At least 1 closed trade must exist in the window

Signal detection (7-day window):
  - Strategy is primed on all but the last bar
  - Last bar is evaluated for a live BUY / SELL / LONG / SHORT signal
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.core.engine import run_backtest
from delta_bt.core.types import RunConfig, Position
from delta_bt.core.registry import load_strategy
from delta_bt.core.strategy import StrategyContext


logger = logging.getLogger(__name__)

_RES_SECONDS = {
    "1m": 60,  "3m": 180,  "5m": 300,  "15m": 900,  "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}
_DEFAULT_RES_SECONDS = 3600
_MIN_BARS_FLOOR = 200   # indicator warmup floor regardless of resolution


@dataclass
class ScannerSetup:
    symbol: str
    resolution: str
    strategy: str
    signal: str             # "BUY" / "SELL" / "LONG" / "SHORT"
    timestamp: datetime
    price: float
    total_pnl: float        # net PnL over the 30-day profitability window
    win_rate: float         # win rate over the 30-day window (0.0 – 1.0)
    trade_count: int        # number of closed trades in the 30-day window


def _bars_needed(lookback_days: int, step_sec: int) -> int:
    """Return bar count for the requested lookback, floored at _MIN_BARS_FLOOR
    so indicator warmup is always satisfied regardless of resolution."""
    return max(_MIN_BARS_FLOOR, (lookback_days * 24 * 3600) // step_sec)


def _calc_profitability(backtest_result) -> Tuple[float, float, int]:
    """Extract (total_pnl, win_rate, trade_count) from a backtest result.

    Supports both dict-style and attribute-style result objects.
    """
    def _get(obj, key, default=0):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    total_pnl   = float(_get(backtest_result, "total_pnl",    0))
    trade_count = int(_get(backtest_result,   "trade_count",  0))

    # Some engines expose win_rate directly; others expose winning_trades count.
    win_rate = float(_get(backtest_result, "win_rate", -1))
    if win_rate < 0:
        winning  = int(_get(backtest_result, "winning_trades", 0))
        win_rate = (winning / trade_count) if trade_count > 0 else 0.0

    return total_pnl, win_rate, trade_count


def _fetch_bars(
    client: DeltaClient,
    symbol: str,
    resolution: str,
    lookback_days: int,
    end_time: datetime,
    label: str,
) -> Optional[List]:
    """Fetch bars for a given lookback window. Returns None on failure."""
    step_sec    = _RES_SECONDS.get(resolution, _DEFAULT_RES_SECONDS)
    needed      = _bars_needed(lookback_days, step_sec)
    start_time  = end_time - timedelta(seconds=step_sec * needed)

    try:
        bars = load_history(client, symbol, resolution, start_time, end_time)
    except Exception as e:
        logger.debug(f"Failed to fetch {label} history for {symbol} {resolution}: {e}")
        return None

    min_bars = max(100, needed // 2)
    if len(bars) < min_bars:
        logger.debug(
            f"Not enough {label} bars for {symbol} {resolution}: "
            f"got {len(bars)}, need {min_bars}"
        )
        return None

    return bars


def _check_symbol_strat(
    client: DeltaClient,
    symbol: str,
    resolution: str,
    strategy_name: str,
    end_time: datetime,
    lookback_days: int = 7,
    profit_lookback_days: int = 30,
    min_win_rate: float = 0.50,
) -> Optional[ScannerSetup]:
    """Run profitability filter (30d) then live signal check (7d).

    Steps:
      1. Fetch 30-day bars and run full backtest — skip if:
           - zero trades (no evidence of profitability)
           - net PnL <= 0
           - win rate < min_win_rate
      2. Fetch 7-day bars, prime strategy on all but last bar.
      3. Evaluate last bar — return ScannerSetup if BUY/SELL/LONG/SHORT.
    """

    # ------------------------------------------------------------------
    # Step 1 — 30-day profitability filter
    # ------------------------------------------------------------------
    profit_bars = _fetch_bars(
        client, symbol, resolution, profit_lookback_days, end_time, "30d"
    )
    if profit_bars is None:
        return None

    try:
        profit_strat = load_strategy(strategy_name, {})
    except SystemExit:
        return None

    profit_cfg = RunConfig(
        strategy=strategy_name,
        symbol=symbol,
        resolution=resolution,
        capital=1000,
        fee_bps=5,
        slippage_bps=2,
    )

    try:
        profit_result = run_backtest(profit_bars, profit_strat, profit_cfg)
    except Exception as e:
        logger.debug(f"30d backtest failed for {symbol} {strategy_name}: {e}")
        return None

    total_pnl, win_rate, trade_count = _calc_profitability(profit_result)

    if trade_count == 0:
        logger.debug(f"Skipping {symbol} {strategy_name} {resolution}: no trades in 30d window")
        return None

    if total_pnl <= 0:
        logger.debug(
            f"Skipping {symbol} {strategy_name} {resolution}: "
            f"30d PnL={total_pnl:.4f} <= 0"
        )
        return None

    if win_rate < min_win_rate:
        logger.debug(
            f"Skipping {symbol} {strategy_name} {resolution}: "
            f"30d win_rate={win_rate:.2%} < {min_win_rate:.2%}"
        )
        return None

    logger.debug(
        f"Profitability passed for {symbol} {strategy_name} {resolution}: "
        f"PnL={total_pnl:.4f}, win_rate={win_rate:.2%}, trades={trade_count}"
    )

    # ------------------------------------------------------------------
    # Step 2 — 7-day signal window: fetch bars and prime strategy
    # ------------------------------------------------------------------
    signal_bars = _fetch_bars(
        client, symbol, resolution, lookback_days, end_time, "7d"
    )
    if signal_bars is None:
        return None

    try:
        signal_strat = load_strategy(strategy_name, {})
    except SystemExit:
        return None

    signal_cfg = RunConfig(
        strategy=strategy_name,
        symbol=symbol,
        resolution=resolution,
        capital=1000,
        fee_bps=5,
        slippage_bps=2,
    )

    try:
        # Prime strategy on all bars except the last so indicator state
        # is fully warmed up before the live-bar evaluation.
        if len(signal_bars) > 1:
            run_backtest(signal_bars[:-1], signal_strat, signal_cfg)

        # Evaluate the last bar for a live signal.
        ctx = StrategyContext(Position(symbol=symbol), 1000, 1000)
        sig = signal_strat.on_bar(signal_bars[-1], ctx)
    except Exception as e:
        logger.debug(f"7d signal evaluation failed for {symbol} {strategy_name}: {e}")
        return None

    # ------------------------------------------------------------------
    # Step 3 — Return setup only if last bar has an actionable signal
    # ------------------------------------------------------------------
    last_signal = sig.name if hasattr(sig, "name") else str(sig)
    if last_signal in ("BUY", "SELL", "LONG", "SHORT"):
        return ScannerSetup(
            symbol=symbol,
            resolution=resolution,
            strategy=strategy_name,
            signal=last_signal,
            timestamp=signal_bars[-1].ts,
            price=float(signal_bars[-1].close),
            total_pnl=total_pnl,
            win_rate=win_rate,
            trade_count=trade_count,
        )

    return None


def scan_strategy_setups(
    client: DeltaClient,
    symbols: List[str],
    resolutions: List[str] = ["15m", "30m", "1h"],
    strategies: List[str] = ["ema3"],
    workers: int = 8,
    lookback_days: int = 7,
    profit_lookback_days: int = 30,
    min_win_rate: float = 0.50,
) -> List[ScannerSetup]:
    """
    Scan for active strategy setups across symbols, resolutions, and strategies.

    Only returns setups where:
      - The strategy was net profitable over the last 30 days (total_pnl > 0)
      - Win rate >= min_win_rate (default 50%) over the last 30 days
      - At least 1 closed trade exists in the 30-day window
      - The latest bar (within the last 7 days) signals BUY / SELL / LONG / SHORT

    Args:
        client:               Authenticated DeltaClient instance.
        symbols:              List of trading symbols to scan.
        resolutions:          List of timeframe resolutions to scan.
        strategies:           List of strategy names to evaluate.
        workers:              Number of concurrent threads.
        lookback_days:        Signal detection window in days (default 7).
        profit_lookback_days: Profitability check window in days (default 30).
        min_win_rate:         Minimum win rate threshold (default 0.50 = 50%).

    Returns:
        List of ScannerSetup objects sorted by timestamp descending, then symbol.
        Each setup includes total_pnl, win_rate, and trade_count from the 30d window.
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
            ex.submit(
                _check_symbol_strat,
                client, sym, res, strat, end_time,
                lookback_days, profit_lookback_days, min_win_rate,
            )
            for (sym, res, strat) in tasks
        ]

        for f in as_completed(futs):
            try:
                result = f.result()
                if result:
                    setups.append(result)
            except Exception as e:
                logger.debug(f"Scanner task raised an exception: {e}")

    setups.sort(key=lambda s: (s.timestamp, s.symbol), reverse=True)
    return setups

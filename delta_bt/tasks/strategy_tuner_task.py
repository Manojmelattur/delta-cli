"""Strategy Tuner Task.

Finds the best strategy and params for a given symbol and timeframe
by running a train/val/test search across all registered strategies.

Called by the task runner as:
    run(symbol="BTCUSD", resolution="1h", metric="sharpe", ...)
"""
from __future__ import annotations

import importlib
import itertools
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type

from delta_bt.core.strategy import Strategy
from delta_bt.core.types import Bar, RunConfig
from delta_bt.data.delta_client import DeltaClient
from delta_bt.core.engine import run_backtest
from delta_bt.store.db import connect
from delta_bt.tuner.strategy_tuner import ParamSpace, StrategyTuner


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

def _default_spaces() -> Dict[Type[Strategy], Dict[str, ParamSpace]]:
    spaces: Dict[Type[Strategy], Dict[str, ParamSpace]] = {}

    def _try(module_path: str, cls_name: str, space: Dict[str, ParamSpace]):
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            spaces[cls] = space
        except (ImportError, AttributeError):
            pass

    _try("delta_bt.strategies.macd", "Macd", {
        "fast":   ParamSpace.int_range(8,  16, step=2),
        "slow":   ParamSpace.int_range(20, 30, step=2),
        "signal": ParamSpace.int_range(7,  11, step=2),
    })
    _try("delta_bt.strategies.macd_divergence", "MacdDivergence", {
        "fast":     ParamSpace.int_range(8,  16, step=4),
        "slow":     ParamSpace.int_range(20, 30, step=4),
        "signal":   ParamSpace.int_range(7,  11, step=2),
        "pivot":    ParamSpace.int_range(2,  5,  step=1),
        "lookback": ParamSpace.int_range(40, 80, step=20),
    })
    _try("delta_bt.strategies.rsi_mr", "RsiMeanRev", {
        "period":     ParamSpace.int_range(10, 20, step=2),
        "oversold":   ParamSpace.float_range(25.0, 35.0, step=5.0),
        "overbought": ParamSpace.float_range(65.0, 75.0, step=5.0),
    })
    _try("delta_bt.strategies.rsi_divergence", "RsiDivergence", {
        "rsi_len":  ParamSpace.int_range(10, 20, step=2),
        "pivot":    ParamSpace.int_range(2,  5,  step=1),
        "lookback": ParamSpace.int_range(40, 80, step=20),
        "rsi_os":   ParamSpace.float_range(25.0, 35.0, step=5.0),
        "rsi_ob":   ParamSpace.float_range(65.0, 75.0, step=5.0),
    })
    _try("delta_bt.strategies.ema3", "ThreeEma", {
        "fast": ParamSpace.int_range(5,  15, step=2),
        "mid":  ParamSpace.int_range(15, 30, step=3),
        "slow": ParamSpace.int_range(40, 70, step=5),
    })
    _try("delta_bt.strategies.fvg", "Fvg", {
        "lookback_close": ParamSpace.int_range(30, 70, step=10),
    })
    _try("delta_bt.strategies.grid", "Grid", {
        "grid_size": ParamSpace.int_range(8,  20, step=4),
        "deviation": ParamSpace.float_range(0.3, 1.0, step=0.2),
    })
    _try("delta_bt.strategies.momentum_breakout", "MomentumBreakout", {
        "lookback": ParamSpace.int_range(8,  20, step=4),
        "vol_mult": ParamSpace.float_range(1.2, 2.0, step=0.2),
    })
    _try("delta_bt.strategies.donchian_breakout", "DonchianBreakout", {
        "enter_len": ParamSpace.int_range(15, 30, step=5),
        "exit_len":  ParamSpace.int_range(5,  15, step=5),
        "atr_len":   ParamSpace.int_range(10, 20, step=5),
    })
    _try("delta_bt.strategies.atr_channel_breakout", "AtrChannelBreakout", {
        "mid_len":  ParamSpace.int_range(15, 30, step=5),
        "atr_len":  ParamSpace.int_range(10, 20, step=5),
        "atr_mult": ParamSpace.float_range(1.5, 3.0, step=0.5),
    })
    _try("delta_bt.strategies.obv_trend", "ObvTrend", {
        "obv_ema_len":   ParamSpace.int_range(10, 30, step=5),
        "price_ema_len": ParamSpace.int_range(30, 70, step=10),
    })
    _try("delta_bt.strategies.stochastic_rsi", "StochasticRsi", {
        "rsi_len":   ParamSpace.int_range(10, 20, step=2),
        "stoch_len": ParamSpace.int_range(10, 20, step=2),
        "smooth_k":  ParamSpace.int_range(2,  5,  step=1),
        "smooth_d":  ParamSpace.int_range(2,  5,  step=1),
    })
    _try("delta_bt.strategies.cci_reversion", "CciReversion", {
        "cci_len":   ParamSpace.int_range(14, 28, step=7),
        "threshold": ParamSpace.float_range(80.0, 120.0, step=20.0),
    })
    _try("delta_bt.strategies.bb_ha_supertrend", "BbHaSupertrend", {
        "bb_len":  ParamSpace.int_range(15, 25, step=5),
        "bb_mult": ParamSpace.float_range(1.5, 2.5, step=0.5),
        "atr_len": ParamSpace.int_range(8,  14, step=3),
        "st_mult": ParamSpace.float_range(2.0, 4.0, step=0.5),
    })
    _try("delta_bt.strategies.supertrend_mom", "SupertrendMomentum", {
        "atr_period": ParamSpace.int_range(8,  14, step=3),
        "multiplier": ParamSpace.float_range(2.0, 4.0, step=0.5),
        "mom_period": ParamSpace.int_range(8,  14, step=3),
        "mom_thresh": ParamSpace.float_range(0.0, 1.0, step=0.5),
    })
    _try("delta_bt.strategies.keltner_squeeze", "KeltnerSqueezeStrategy", {
        "bb_period": ParamSpace.int_range(15, 25, step=5),
        "kc_period": ParamSpace.int_range(15, 25, step=5),
        "kc_mult":   ParamSpace.float_range(1.0, 2.0, step=0.5),
    })
    _try("delta_bt.strategies.vwap", "Vwap", {
        "band_bps": ParamSpace.int_range(10, 40, step=10),
        "mode":     ParamSpace.choices(["trend", "revert"]),
    })
    _try("delta_bt.strategies.vwap_bands", "VwapBands", {
        "mult":      ParamSpace.float_range(1.5, 2.5, step=0.5),
        "stdev_len": ParamSpace.int_range(30, 70, step=20),
        "rsi_len":   ParamSpace.int_range(10, 20, step=5),
    })
    _try("delta_bt.strategies.smc_bos_retest", "SmcBosRetest", {
        "swing":         ParamSpace.int_range(3,  7,  step=2),
        "retest_window": ParamSpace.int_range(10, 30, step=10),
        "buffer_pct":    ParamSpace.float_range(0.1, 0.5, step=0.2),
    })
    _try("delta_bt.strategies.smc_choch_bos", "SmcChoChBos", {
        "swing": ParamSpace.int_range(3, 7, step=2),
    })
    _try("delta_bt.strategies.smc_liquidity_sweep", "SmcLiquiditySweep", {
        "lookback":   ParamSpace.int_range(10, 30, step=10),
        "wick_ratio": ParamSpace.float_range(0.3, 0.7, step=0.2),
        "cooldown":   ParamSpace.int_range(2,  6,  step=2),
    })
    _try("delta_bt.strategies.smc_ob", "SmcOrderBlock", {
        "impulse_bars": ParamSpace.int_range(2,  5,  step=1),
        "impulse_mult": ParamSpace.float_range(1.0, 2.0, step=0.5),
        "max_age":      ParamSpace.int_range(30, 70, step=20),
    })
    _try("delta_bt.strategies.inside_bar_breakout", "InsideBarBreakout", {
        "ema_len":        ParamSpace.int_range(30, 70, step=20),
        "breakout_bars":  ParamSpace.int_range(2,  5,  step=1),
        "min_body_ratio": ParamSpace.float_range(0.2, 0.5, step=0.1),
    })
    _try("delta_bt.strategies.three_bar_reversal", "ThreeBarReversal", {
        "ema_len":      ParamSpace.int_range(30, 70, step=20),
        "confirm_bars": ParamSpace.int_range(1,  3,  step=1),
        "min_move_pct": ParamSpace.float_range(0.05, 0.2, step=0.05),
    })
    _try("delta_bt.strategies.engulfing", "Engulfing", {
        "ema_len":        ParamSpace.int_range(30, 70, step=20),
        "min_body_ratio": ParamSpace.float_range(1.0, 1.5, step=0.2),
        "close_frac":     ParamSpace.float_range(0.5, 0.8, step=0.1),
    })
    _try("delta_bt.strategies.pin_bar", "PinBar", {
        "ema_len":    ParamSpace.int_range(30, 70, step=20),
        "wick_ratio": ParamSpace.float_range(1.5, 3.0, step=0.5),
        "swing":      ParamSpace.int_range(3,  7,  step=2),
    })

    return spaces


# ---------------------------------------------------------------------------
# Bar loader — fetches from DeltaClient, mirrors atr_position_sizer pattern
# ---------------------------------------------------------------------------

def _load_bars(
    symbol: str,
    resolution: str,
    days_back: int,
) -> List[Bar]:
    client   = DeltaClient(base_url="https://api.india.delta.exchange")
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days_back)

    raw = client.candles(symbol, resolution, start_time, end_time)
    if not raw:
        raise ValueError(
            f"No candles returned for symbol='{symbol}' "
            f"resolution='{resolution}'."
        )

    bars: List[Bar] = []
    for c in raw:
        bars.append(Bar(
            ts=datetime.fromisoformat(str(c["time"]).replace("Z", "+00:00"))
            if isinstance(c["time"], str)
            else datetime.fromtimestamp(float(c["time"]), tz=timezone.utc),
            symbol=symbol,
            open=float(c["open"]),
            high=float(c["high"]),
            low=float(c["low"]),
            close=float(c["close"]),
            volume=float(c.get("volume") or 0.0),
            resolution="1h"
        ))

    # Ensure chronological order.
    bars.sort(key=lambda b: b.ts)
    return bars


# ---------------------------------------------------------------------------
# Persist result
# ---------------------------------------------------------------------------

def _persist_result(
    symbol: str,
    resolution: str,
    metric: str,
    best_strategy: str,
    best_params: Dict[str, Any],
    val_score: float,
    test_score: float,
    n_trials: int,
    tag: Optional[str],
) -> int:
    now = datetime.now(timezone.utc).isoformat() + "Z"
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tuner_results (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT    NOT NULL,
                symbol        TEXT    NOT NULL,
                resolution    TEXT    NOT NULL,
                metric        TEXT    NOT NULL,
                best_strategy TEXT    NOT NULL,
                best_params   TEXT    NOT NULL,
                val_score     REAL    NOT NULL,
                test_score    REAL    NOT NULL,
                n_trials      INTEGER NOT NULL,
                tag           TEXT
            )
            """
        )
        cur = conn.execute(
            """
            INSERT INTO tuner_results
                (ts, symbol, resolution, metric, best_strategy,
                 best_params, val_score, test_score, n_trials, tag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now, symbol, resolution, metric,
                best_strategy,
                json.dumps(best_params),
                val_score, test_score,
                n_trials, tag,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


# ---------------------------------------------------------------------------
# Main task entry point — matches **kwargs pattern of all other tasks
# ---------------------------------------------------------------------------

def run(**kwargs):
    """
    Strategy Tuner Task.

    Kwargs:
        symbol        (str,   default "BTCUSD")     — Trading symbol.
        resolution    (str,   default "1h")          — Bar resolution.
        metric        (str,   default "sharpe")      — sharpe | sortino |
                                                       calmar | profit_factor |
                                                       win_rate | total_return.
        method        (str,   default "random")      — random | grid.
        n_trials      (int,   default 50)            — Trials per strategy.
        train_frac    (float, default 0.6)           — Train split fraction.
        val_frac      (float, default 0.2)           — Val split fraction.
        capital       (float, default 10000)         — Starting capital.
        fee_bps       (float, default 5.0)           — Fee in basis points.
        slippage_bps  (float, default 2.0)           — Slippage in bps.
        sl_pct        (float, default 1.5)           — Stop-loss %.
        tp_pct        (float, default 0.0)           — Take-profit %.
        trail_pct     (float, default 0.0)           — Trailing stop %.
        leverage      (float, default 1.0)           — Leverage multiplier.
        qty_pct       (float, default 1.0)           — Equity fraction per trade.
        adx_filter    (bool,  default False)         — Enable ADX filter.
        adx_len       (int,   default 14)            — ADX period.
        adx_trend_min (float, default 25.0)          — ADX trend threshold.
        adx_range_max (float, default 20.0)          — ADX range threshold.
        n_jobs        (int,   default 1)             — Parallel workers.
        seed          (int,   default 42)            — Random seed.
        min_trades    (int,   default 5)             — Min val trades to qualify.
        days_back     (int,   default 90)            — Days of history to fetch.
        tag           (str,   default None)          — Label for this run.
        strategies    (list,  default None)          — Restrict to named strategies.
    """
    symbol       = str(kwargs.get("symbol",       "BTCUSD"))
    resolution   = str(kwargs.get("resolution",   "1h"))
    metric       = str(kwargs.get("metric",       "sharpe"))
    method       = str(kwargs.get("method",       "random"))
    n_trials     = int(kwargs.get("n_trials",     50))
    train_frac   = float(kwargs.get("train_frac", 0.6))
    val_frac     = float(kwargs.get("val_frac",   0.2))
    capital      = float(kwargs.get("capital",    10_000.0))
    fee_bps      = float(kwargs.get("fee_bps",    5.0))
    slippage_bps = float(kwargs.get("slippage_bps", 2.0))
    sl_pct       = float(kwargs.get("sl_pct",     1.5))
    tp_pct       = float(kwargs.get("tp_pct",     0.0))
    trail_pct    = float(kwargs.get("trail_pct",  0.0))
    leverage     = float(kwargs.get("leverage",   1.0))
    qty_pct      = float(kwargs.get("qty_pct",    1.0))
    adx_filter   = bool(kwargs.get("adx_filter",  False))
    adx_len      = int(kwargs.get("adx_len",      14))
    adx_trend_min = float(kwargs.get("adx_trend_min", 25.0))
    adx_range_max = float(kwargs.get("adx_range_max", 20.0))
    n_jobs       = int(kwargs.get("n_jobs",       1))
    seed         = int(kwargs.get("seed",         42))
    min_trades   = int(kwargs.get("min_trades",   5))
    days_back    = int(kwargs.get("days_back",    90))
    tag          = kwargs.get("tag",              None)
    strategies   = kwargs.get("strategies",       None)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Load bars from Delta Exchange ---
    try:
        bars = _load_bars(symbol, resolution, days_back)
    except Exception as e:
        return (
            f"### Strategy Tuner\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Failed to load bars for {symbol} {resolution}: {e}\n"
        )

    n_bars = len(bars)
    if n_bars < 100:
        return (
            f"### Strategy Tuner\n\n"
            f"Date: {now_str}\n\n"
            f"WARN | Insufficient bars for {symbol} {resolution}: "
            f"found {n_bars}, need at least 100. "
            f"Try increasing days_back.\n"
        )

    # --- Build RunConfig from kwargs ---
    cfg = RunConfig(
        symbol=symbol,
        strategy="tuner",
        resolution=resolution,
        capital=capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        trail_pct=trail_pct,
        leverage=leverage,
        qty_pct=qty_pct,
        adx_filter=adx_filter,
        adx_len=adx_len,
        adx_trend_min=adx_trend_min,
        adx_range_max=adx_range_max,
        adx_exit_on_flip=False,
        adx_tighten_trail_on_flip=0.0,
        record_diagnostics=False,
    )

    # --- Build param spaces ---
    all_spaces = _default_spaces()

    if strategies:
        all_spaces = {
            cls: space
            for cls, space in all_spaces.items()
            if getattr(cls, "name", None) in strategies
        }
        if not all_spaces:
            return (
                f"### Strategy Tuner\n\n"
                f"Date: {now_str}\n\n"
                f"ERR | None of the requested strategies were found: "
                f"{strategies}.\n"
            )

    n_strategies = len(all_spaces)

    # --- Run tuner ---
    try:
        tuner = StrategyTuner(
            spaces=all_spaces,
            bars=bars,
            cfg=cfg,
            metric=metric,
            method=method,
            n_trials=n_trials,
            train_frac=train_frac,
            val_frac=val_frac,
            n_jobs=n_jobs,
            seed=seed,
            min_trades=min_trades,
        )
        result = tuner.run()
    except Exception as e:
        return (
            f"### Strategy Tuner\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Tuner failed: {e}\n"
        )

    # --- Persist result ---
    try:
        row_id = _persist_result(
            symbol=symbol,
            resolution=resolution,
            metric=metric,
            best_strategy=result.best_strategy_name,
            best_params=result.best_params,
            val_score=result.best_val_score,
            test_score=result.best_test_score,
            n_trials=len(result.all_trials),
            tag=tag,
        )
    except Exception as e:
        row_id = 0  # persist failure should not block the report

    # --- Split sizes ---
    n_train = int(n_bars * train_frac)
    n_val   = int(n_bars * val_frac)
    n_test  = n_bars - n_train - n_val

    # --- Top 10 trials table ---
    top      = result.top_n(10)
    top_rows = ""
    for i, t in enumerate(top, 1):
        params_str = ", ".join(f"{k}={v}" for k, v in t.params.items())
        top_rows += (
            f"| {i} | {t.strategy_name} | {t.val_score:.4f} | "
            f"{t.test_score:.4f} | {t.n_trades_val} | {params_str} |\n"
        )

    # --- Strategy coverage table ---
    strategy_names = sorted(set(t.strategy_name for t in result.all_trials))
    coverage_rows  = ""
    for name in strategy_names:
        trials    = [t for t in result.all_trials if t.strategy_name == name]
        best_val  = max(t.val_score  for t in trials)
        best_test = max(t.test_score for t in trials)
        coverage_rows += (
            f"| {name} | {len(trials)} | {best_val:.4f} | {best_test:.4f} |\n"
        )

    # --- Report ---
    report = f"""### Strategy Tuner

Date      : {now_str}
Result ID : {row_id}
Symbol    : {symbol}
Resolution: {resolution}
Metric    : {metric}
Method    : {method}
Tag       : {tag or '—'}

#### Data Split

| Segment | Bars   | Fraction |
| :------ | :----- | :------- |
| Train   | {n_train} | {train_frac:.0%} |
| Val     | {n_val}   | {val_frac:.0%} |
| Test    | {n_test}  | {1 - train_frac - val_frac:.0%} |
| Total   | {n_bars}  | 100% |

#### Best Result

| Field            | Value |
| :--------------- | :---- |
| Strategy         | **{result.best_strategy_name}** |
| Params           | `{result.best_params}` |
| Val {metric:14s} | {result.best_val_score:.4f} |
| Test {metric:13s} | **{result.best_test_score:.4f}** |

#### Search Coverage

| Strategy | Trials | Best Val | Best Test |
| :------- | :----- | :------- | :-------- |
{coverage_rows}
#### Top 10 Trials (by Val Score)

| Rank | Strategy | Val Score | Test Score | Val Trades | Params |
| :--- | :------- | :-------- | :--------- | :--------- | :----- |
{top_rows}
#### Configuration

| Param        | Value |
| :----------- | :---- |
| Capital      | ${capital:,.0f} |
| Fee          | {fee_bps} bps |
| Slippage     | {slippage_bps} bps |
| SL %         | {sl_pct or '—'} |
| TP %         | {tp_pct or '—'} |
| Trail %      | {trail_pct or '—'} |
| Leverage     | {leverage}x |
| ADX Filter   | {'on' if adx_filter else 'off'} |
| Days back    | {days_back} |
| Strategies   | {n_strategies} |
| Trials run   | {len(result.all_trials)} |
| Workers      | {n_jobs} |
| Seed         | {seed} |

System Status: Tuner completed successfully.
"""
    return report

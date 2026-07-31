"""Strategy Tuner — finds optimal params for one or more strategies.

Runs a grid or random search over param spaces, evaluates each combination
on a train split, selects the best on a validation split, and reports
honest performance on a held-out test split.

Supports cross-strategy selection: pass multiple strategy classes and the
tuner returns the best (strategy_class, params) pair across all of them.

Usage:
    from delta_bt.tuner import StrategyTuner, ParamSpace

    spaces = {
        Macd: {
            "fast":   ParamSpace.int_range(8, 16, step=2),
            "slow":   ParamSpace.int_range(20, 30, step=2),
            "signal": ParamSpace.int_range(7, 11, step=1),
        },
        RsiMeanRev: {
            "period":    ParamSpace.int_range(10, 20, step=2),
            "oversold":  ParamSpace.float_range(25, 35, step=5),
            "overbought":ParamSpace.float_range(65, 75, step=5),
        },
    }

    tuner = StrategyTuner(
        spaces=spaces,
        bars=bars,
        cfg=base_cfg,
        metric="sharpe",
        method="random",
        n_trials=100,
        train_frac=0.6,
        val_frac=0.2,
        n_jobs=4,
    )
    result = tuner.run()
    print(result.summary())
"""
from __future__ import annotations

import copy
import itertools
import math
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from .core.strategy import Strategy
from .core.types import Bar, RunConfig
from .engine.backtest import run_backtest
from .execution.portfolio import Portfolio


# ---------------------------------------------------------------------------
# Param space helpers
# ---------------------------------------------------------------------------

class ParamSpace:
    """Defines the search space for a single parameter."""

    def __init__(self, values: List[Any]):
        self.values = values

    @staticmethod
    def int_range(lo: int, hi: int, step: int = 1) -> "ParamSpace":
        """Inclusive integer range."""
        return ParamSpace(list(range(lo, hi + 1, step)))

    @staticmethod
    def float_range(lo: float, hi: float, step: float = 0.1) -> "ParamSpace":
        """Inclusive float range."""
        vals: List[float] = []
        v = lo
        while v <= hi + 1e-9:
            vals.append(round(v, 10))
            v += step
        return ParamSpace(vals)

    @staticmethod
    def choices(options: List[Any]) -> "ParamSpace":
        """Explicit list of values."""
        return ParamSpace(list(options))


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

def _returns(pf: Portfolio) -> List[float]:
    """Bar-by-bar equity returns from the equity curve."""
    eq = [pt.equity for pt in pf.equity_curve]
    if len(eq) < 2:
        return []
    return [(eq[i] - eq[i - 1]) / eq[i - 1] for i in range(1, len(eq)) if eq[i - 1] != 0]


def _sharpe(pf: Portfolio, periods_per_year: int = 252) -> float:
    rets = _returns(pf)
    if len(rets) < 2:
        return -999.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def _sortino(pf: Portfolio, periods_per_year: int = 252) -> float:
    rets = _returns(pf)
    if len(rets) < 2:
        return -999.0
    mean = sum(rets) / len(rets)
    neg = [r for r in rets if r < 0]
    if not neg:
        return 999.0
    down_var = sum(r ** 2 for r in neg) / len(neg)
    down_std = math.sqrt(down_var)
    if down_std == 0:
        return 0.0
    return (mean / down_std) * math.sqrt(periods_per_year)


def _calmar(pf: Portfolio, periods_per_year: int = 252) -> float:
    eq = [pt.equity for pt in pf.equity_curve]
    if len(eq) < 2:
        return -999.0
    # Annualised return.
    total_return = (eq[-1] - eq[0]) / eq[0] if eq[0] != 0 else 0.0
    n_years = len(eq) / periods_per_year
    ann_return = (1 + total_return) ** (1 / max(n_years, 1e-9)) - 1
    # Max drawdown.
    peak = eq[0]
    max_dd = 0.0
    for e in eq:
        peak = max(peak, e)
        dd = (peak - e) / peak if peak != 0 else 0.0
        max_dd = max(max_dd, dd)
    if max_dd == 0:
        return 999.0
    return ann_return / max_dd


def _profit_factor(pf: Portfolio) -> float:
    gross_profit = sum(t.pnl for t in pf.trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in pf.trades if t.pnl < 0))
    if gross_loss == 0:
        return 999.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _win_rate(pf: Portfolio) -> float:
    if not pf.trades:
        return 0.0
    wins = sum(1 for t in pf.trades if t.pnl > 0)
    return wins / len(pf.trades)


def _total_return(pf: Portfolio) -> float:
    eq = [pt.equity for pt in pf.equity_curve]
    if len(eq) < 2 or eq[0] == 0:
        return -999.0
    return (eq[-1] - eq[0]) / eq[0]


METRICS = {
    "sharpe":        _sharpe,
    "sortino":       _sortino,
    "calmar":        _calmar,
    "profit_factor": _profit_factor,
    "win_rate":      _win_rate,
    "total_return":  _total_return,
}


# ---------------------------------------------------------------------------
# Trial result
# ---------------------------------------------------------------------------

@dataclass
class TrialResult:
    strategy_name: str
    params: Dict[str, Any]
    train_score: float
    val_score: float
    test_score: float
    n_trades_train: int
    n_trades_val: int
    n_trades_test: int
    metric: str


# ---------------------------------------------------------------------------
# Tuner result
# ---------------------------------------------------------------------------

@dataclass
class TunerResult:
    best_strategy_name: str
    best_params: Dict[str, Any]
    best_val_score: float
    best_test_score: float
    metric: str
    all_trials: List[TrialResult] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "StrategyTuner Result",
            "=" * 60,
            f"  Best strategy : {self.best_strategy_name}",
            f"  Best params   : {self.best_params}",
            f"  Metric        : {self.metric}",
            f"  Val score     : {self.best_val_score:.4f}",
            f"  Test score    : {self.best_test_score:.4f}",
            f"  Total trials  : {len(self.all_trials)}",
            "=" * 60,
        ]
        return "\n".join(lines)

    def top_n(self, n: int = 10) -> List[TrialResult]:
        """Return top N trials sorted by validation score descending."""
        return sorted(self.all_trials, key=lambda t: t.val_score, reverse=True)[:n]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_cfg(base_cfg: RunConfig, extra: Dict[str, Any]) -> RunConfig:
    """Return a shallow copy of base_cfg with extra fields overridden."""
    cfg = copy.copy(base_cfg)
    for k, v in extra.items():
        setattr(cfg, k, v)
    return cfg


def _score(
    strategy_cls: Type[Strategy],
    params: Dict[str, Any],
    bars: List[Bar],
    cfg: RunConfig,
    metric: str,
) -> Tuple[float, int]:
    """Run a single backtest and return (score, n_trades)."""
    strat = strategy_cls(params)
    pf = run_backtest(bars, strat, cfg)
    score = METRICS[metric](pf)
    return score, len(pf.trades)


def _run_trial(args: Tuple) -> TrialResult:
    """Top-level function for ProcessPoolExecutor (must be picklable)."""
    (
        strategy_cls,
        params,
        train_bars,
        val_bars,
        test_bars,
        cfg,
        metric,
    ) = args
    train_score, n_train = _score(strategy_cls, params, train_bars, cfg, metric)
    val_score,   n_val   = _score(strategy_cls, params, val_bars,   cfg, metric)
    test_score,  n_test  = _score(strategy_cls, params, test_bars,  cfg, metric)
    return TrialResult(
        strategy_name=getattr(strategy_cls, "name", strategy_cls.__name__),
        params=params,
        train_score=train_score,
        val_score=val_score,
        test_score=test_score,
        n_trades_train=n_train,
        n_trades_val=n_val,
        n_trades_test=n_test,
        metric=metric,
    )


def _grid_combinations(space: Dict[str, ParamSpace]) -> List[Dict[str, Any]]:
    """Enumerate all combinations in a param space."""
    keys = list(space.keys())
    value_lists = [space[k].values for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*value_lists)]


def _random_combinations(
    space: Dict[str, ParamSpace],
    n: int,
    seed: Optional[int],
) -> List[Dict[str, Any]]:
    """Sample n random combinations from a param space."""
    rng = random.Random(seed)
    combos = []
    for _ in range(n):
        combos.append({k: rng.choice(v.values) for k, v in space.items()})
    return combos


# ---------------------------------------------------------------------------
# StrategyTuner
# ---------------------------------------------------------------------------

class StrategyTuner:
    """
    Finds the best strategy and params for a given bar feed.

    Args:
        spaces      : Dict mapping strategy class → Dict[param_name, ParamSpace].
        bars        : Full historical bar list.
        cfg         : Base RunConfig (fees, slippage, stops, etc.).
        metric      : Optimisation target. One of:
                      "sharpe", "sortino", "calmar",
                      "profit_factor", "win_rate", "total_return".
        method      : "grid" or "random".
        n_trials    : Number of random trials per strategy (ignored for grid).
        train_frac  : Fraction of bars used for training.
        val_frac    : Fraction of bars used for validation.
                      Remaining bars form the test set.
        n_jobs      : Parallel workers (1 = serial).
        seed        : Random seed for reproducibility.
        min_trades  : Minimum trades required on val set to consider a trial
                      valid. Trials below this threshold are penalised.
    """

    def __init__(
        self,
        spaces: Dict[Type[Strategy], Dict[str, ParamSpace]],
        bars: List[Bar],
        cfg: RunConfig,
        metric: str = "sharpe",
        method: str = "random",
        n_trials: int = 100,
        train_frac: float = 0.6,
        val_frac: float = 0.2,
        n_jobs: int = 1,
        seed: Optional[int] = 42,
        min_trades: int = 5,
    ):
        if metric not in METRICS:
            raise ValueError(
                f"Unknown metric '{metric}'. Choose from: {list(METRICS.keys())}"
            )
        if method not in ("grid", "random"):
            raise ValueError(f"Unknown method '{method}'. Choose 'grid' or 'random'.")
        if train_frac + val_frac >= 1.0:
            raise ValueError("train_frac + val_frac must be < 1.0 to leave a test set.")
        if len(bars) < 100:
            raise ValueError("Need at least 100 bars to split into train/val/test.")

        self.spaces = spaces
        self.bars = bars
        self.cfg = cfg
        self.metric = metric
        self.method = method
        self.n_trials = n_trials
        self.train_frac = train_frac
        self.val_frac = val_frac
        self.n_jobs = n_jobs
        self.seed = seed
        self.min_trades = min_trades

        # Split bars once — same split used for all strategies.
        n = len(bars)
        t_end = int(n * train_frac)
        v_end = int(n * (train_frac + val_frac))
        self._train_bars = bars[:t_end]
        self._val_bars   = bars[t_end:v_end]
        self._test_bars  = bars[v_end:]

    def _build_trials(
        self,
        strategy_cls: Type[Strategy],
        space: Dict[str, ParamSpace],
    ) -> List[Dict[str, Any]]:
        if self.method == "grid":
            return _grid_combinations(space)
        return _random_combinations(space, self.n_trials, self.seed)

    def _penalise_low_trades(self, result: TrialResult) -> float:
        """Return val_score, penalised to -999 if too few trades on val set."""
        if result.n_trades_val < self.min_trades:
            return -999.0
        return result.val_score

    def run(self) -> TunerResult:
        """Execute the full tuning run and return a TunerResult."""
        all_args: List[Tuple] = []

        for strategy_cls, space in self.spaces.items():
            combos = self._build_trials(strategy_cls, space)
            for params in combos:
                all_args.append((
                    strategy_cls,
                    params,
                    self._train_bars,
                    self._val_bars,
                    self._test_bars,
                    self.cfg,
                    self.metric,
                ))

        all_trials: List[TrialResult] = []

        if self.n_jobs == 1:
            # Serial execution.
            for args in all_args:
                try:
                    trial = _run_trial(args)
                    all_trials.append(trial)
                except Exception:
                    pass  # skip failed trials silently
        else:
            # Parallel execution.
            with ProcessPoolExecutor(max_workers=self.n_jobs) as executor:
                futures = {executor.submit(_run_trial, args): args for args in all_args}
                for future in as_completed(futures):
                    try:
                        trial = future.result()
                        all_trials.append(trial)
                    except Exception:
                        pass  # skip failed trials silently

        if not all_trials:
            raise RuntimeError("All trials failed. Check strategy implementations and bar data.")

        # Select best trial by penalised validation score.
        best = max(all_trials, key=self._penalise_low_trades)

        return TunerResult(
            best_strategy_name=best.strategy_name,
            best_params=best.params,
            best_val_score=best.val_score,
            best_test_score=best.test_score,
            metric=self.metric,
            all_trials=all_trials,
        )

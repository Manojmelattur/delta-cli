"""Core data types shared across the framework."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"      # close any open position
    HOLD = "HOLD"      # do nothing


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Bar:
    ts: datetime          # bar close time (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
    resolution: str


@dataclass
class Fill:
    ts: datetime
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float = 0.0
    tag: str = ""         # "entry" / "exit" / free-form


@dataclass
class Position:
    symbol: str
    side: Optional[Side] = None
    qty: float = 0.0
    avg_price: float = 0.0
    opened_at: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        return self.qty > 0 and self.side is not None

    def unrealized(self, mark: float) -> float:
        if not self.is_open:
            return 0.0
        d = mark - self.avg_price
        return d * self.qty if self.side == Side.LONG else -d * self.qty


@dataclass
class Trade:
    """A completed round-trip (entry -> exit)."""
    symbol: str
    side: Side
    qty: float
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime
    exit_price: float
    pnl: float
    fees: float = 0.0
    trade_id: int = 0  # 1-based; joins to diagnostics.csv trade_id column


    @property
    def return_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        d = (self.exit_price - self.entry_price) / self.entry_price
        return d if self.side == Side.LONG else -d


@dataclass
class EquityPoint:
    ts: datetime
    equity: float
    cash: float
    position_value: float


@dataclass
class RunConfig:
    strategy: str
    symbol: str
    resolution: str
    capital: float
    params: dict = field(default_factory=dict)
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    fee_bps: float = 5.0          # 0.05% per side
    slippage_bps: float = 2.0
    qty_pct: float = 1.0          # % of equity to deploy per trade
    sl_pct: float = 0.0           # stop-loss % (0 disables)
    tp_pct: float = 0.0           # take-profit % (0 disables)
    trail_pct: float = 0.0        # trailing stop % (0 disables)
    leverage: float = 1.0         # futures leverage multiplier
    # --- regime filter (off by default → 100% backward compatible) ---
    adx_filter: bool = False      # when True, veto entries that don't match regime
    adx_len: int = 14
    adx_trend_min: float = 20.0   # ADX >= this  → "trend" regime
    adx_range_max: float = 20.0   # ADX <  this  → "range" regime
    # --- regime-aware exits (also opt-in) ---
    adx_exit_on_flip: bool = False           # close position when regime no longer matches
    adx_tighten_trail_on_flip: float = 0.0   # if >0, override trail_pct to this while mismatched
    # --- diagnostics ---
    record_diagnostics: bool = False   # append per-bar ADX/regime/stop rows to pf.diag

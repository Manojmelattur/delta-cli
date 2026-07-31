"""Portfolio & simulated matching engine (used by backtest + paper sim).

Supports engine-level risk management: stop-loss, take-profit, trailing stop
(all as percentages of entry price). These are enforced intrabar on high/low.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..core.types import Bar, EquityPoint, Fill, Position, Side, Signal, Trade


class Portfolio:
    def __init__(
        self,
        starting_cash: float,
        fee_bps: float = 5.0,
        slippage_bps: float = 2.0,
        sl_pct: float = 0.0,      # 0 disables. e.g. 1.5 => 1.5%
        tp_pct: float = 0.0,
        trail_pct: float = 0.0,   # trailing stop as % below peak (LONG) / above trough (SHORT)
        leverage: float = 1.0,
    ):
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.trail_pct = trail_pct
        self.leverage = leverage

        self.position = Position(symbol="")
        self.fills: List[Fill] = []
        self.trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []
        self.diag: List[dict] = []  # per-bar diagnostics (opt-in, filled by engine)

        self._entry_ts: Optional[datetime] = None
        self._entry_price: float = 0.0
        self._entry_fees: float = 0.0
        self._peak: float = 0.0      # for trailing stop
        self._trough: float = 0.0
        self._trade_counter: int = 0
        self._current_trade_id: Optional[int] = None
        self._last_closed_trade_id: Optional[int] = None


    # ------------------------------------------------------------------
    def _apply_slippage(self, price: float, side: Side) -> float:
        adj = price * (self.slippage_bps / 10_000)
        return price + adj if side == Side.LONG else price - adj

    def _fee(self, notional: float) -> float:
        return abs(notional) * (self.fee_bps / 10_000)

    # ------------------------------------------------------------------
    def equity(self, mark: float) -> float:
        return self.cash + self.position.unrealized(mark) + (
            self.position.qty * self.position.avg_price
            if self.position.is_open else 0.0
        )

    # ------------------------------------------------------------------
    def _open(self, bar: Bar, side: Side, qty: float, price: Optional[float] = None):
        px = self._apply_slippage(price if price is not None else bar.close, side)
        notional = px * qty
        fee = self._fee(notional)
        self.cash -= notional + fee
        self.position = Position(
            symbol=bar.symbol, side=side, qty=qty,
            avg_price=px, opened_at=bar.ts,
        )
        self.fills.append(Fill(bar.ts, bar.symbol, side, qty, px, fee, "entry"))
        self._entry_ts = bar.ts
        self._entry_price = px
        self._entry_fees = fee
        self._peak = px
        self._trough = px
        self._trade_counter += 1
        self._current_trade_id = self._trade_counter


    def _close(self, bar: Bar, price: Optional[float] = None, tag: str = "exit"):
        if not self.position.is_open:
            return
        side = self.position.side
        exit_side = Side.SHORT if side == Side.LONG else Side.LONG
        px = self._apply_slippage(price if price is not None else bar.close, exit_side)
        qty = self.position.qty
        notional = px * qty
        fee = self._fee(notional)
        if side == Side.LONG:
            self.cash += notional - fee
            pnl = (px - self.position.avg_price) * qty - fee - self._entry_fees
        else:
            self.cash += (self.position.avg_price - px) * qty + \
                         self.position.avg_price * qty - fee
            pnl = (self.position.avg_price - px) * qty - fee - self._entry_fees

        self.fills.append(Fill(bar.ts, bar.symbol, exit_side, qty, px, fee, tag))
        self.trades.append(Trade(
            symbol=bar.symbol, side=side, qty=qty,
            entry_ts=self._entry_ts, entry_price=self.position.avg_price,
            exit_ts=bar.ts, exit_price=px,
            pnl=pnl, fees=fee + self._entry_fees,
            trade_id=self._current_trade_id or 0,
        ))
        self.position = Position(symbol=bar.symbol)
        self._entry_ts = None
        self._entry_price = 0.0
        self._entry_fees = 0.0
        self._last_closed_trade_id = self._current_trade_id
        self._current_trade_id = None


    # ------------------------------------------------------------------
    def _check_risk_intrabar(self, bar: Bar) -> bool:
        """Trigger SL/TP/trailing based on this bar's H/L. Returns True if closed."""
        if not self.position.is_open:
            return False
        entry = self.position.avg_price
        side = self.position.side

        # update peak/trough for trailing
        if side == Side.LONG:
            self._peak = max(self._peak, bar.high)
        else:
            self._trough = min(self._trough, bar.low)

        sl_px = tp_px = trail_px = None
        if side == Side.LONG:
            if self.sl_pct > 0:    sl_px    = entry * (1 - self.sl_pct / 100)
            if self.tp_pct > 0:    tp_px    = entry * (1 + self.tp_pct / 100)
            if self.trail_pct > 0: trail_px = self._peak * (1 - self.trail_pct / 100)
            # Pessimistic: SL first if both possible within the bar
            hit_sl = sl_px is not None and bar.low <= sl_px
            hit_trail = trail_px is not None and bar.low <= trail_px
            hit_tp = tp_px is not None and bar.high >= tp_px
            if hit_sl:
                self._close(bar, price=sl_px, tag="stop_loss"); return True
            if hit_trail:
                self._close(bar, price=trail_px, tag="trailing_stop"); return True
            if hit_tp:
                self._close(bar, price=tp_px, tag="take_profit"); return True
        else:  # SHORT
            if self.sl_pct > 0:    sl_px    = entry * (1 + self.sl_pct / 100)
            if self.tp_pct > 0:    tp_px    = entry * (1 - self.tp_pct / 100)
            if self.trail_pct > 0: trail_px = self._trough * (1 + self.trail_pct / 100)
            hit_sl = sl_px is not None and bar.high >= sl_px
            hit_trail = trail_px is not None and bar.high >= trail_px
            hit_tp = tp_px is not None and bar.low <= tp_px
            if hit_sl:
                self._close(bar, price=sl_px, tag="stop_loss"); return True
            if hit_trail:
                self._close(bar, price=trail_px, tag="trailing_stop"); return True
            if hit_tp:
                self._close(bar, price=tp_px, tag="take_profit"); return True
        return False

    # ------------------------------------------------------------------
    def handle_signal(self, sig: Signal, bar: Bar, qty_pct: float = 1.0):
        # 1) risk checks intrabar first
        risk_closed = self._check_risk_intrabar(bar)

        if sig in (Signal.HOLD, None):
            self._mark(bar)
            return

        target_side: Optional[Side] = {
            Signal.BUY: Side.LONG,
            Signal.SELL: Side.SHORT,
            Signal.FLAT: None,
        }.get(sig)

        current = self.position.side if self.position.is_open else None
        if target_side == current and not risk_closed:
            self._mark(bar); return

        if self.position.is_open:
            self._close(bar)

        if target_side is not None:
            equity_now = self.cash
            deploy = equity_now * qty_pct * self.leverage
            qty = max(deploy / bar.close, 0.0)
            if qty > 0:
                self._open(bar, target_side, qty)

        self._mark(bar)

    def _mark(self, bar: Bar):
        eq = self.cash + self.position.unrealized(bar.close) + (
            self.position.qty * self.position.avg_price
            if self.position.is_open else 0.0
        )
        pos_val = (self.position.qty * bar.close) if self.position.is_open else 0.0
        self.equity_curve.append(EquityPoint(bar.ts, eq, self.cash, pos_val))

    def force_close(self, bar: Bar):
        if self.position.is_open:
            self._close(bar, tag="force_close")
        self._mark(bar)

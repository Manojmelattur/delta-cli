"""Backtest engine: iterate historical bars, feed strategy, execute in sim."""
from __future__ import annotations

from typing import List

from ..core.strategy import Strategy, StrategyContext
from ..core.types import Bar, RunConfig, Side, Signal
from ..execution.portfolio import Portfolio
from .indicators import ADX


def _regime_allows(strat_regime: str, adx_val: float | None, cfg: RunConfig) -> bool:
    """Whether the strategy's regime matches the current market."""
    if strat_regime == "any":
        return True
    if adx_val is None:
        return True
    if strat_regime == "trend":
        return adx_val >= cfg.adx_trend_min
    if strat_regime == "range":
        return adx_val < cfg.adx_range_max
    return True


def _regime_label(strat_regime: str, adx_val: float | None, cfg: RunConfig) -> str:
    if adx_val is None:
        return "warmup"
    if adx_val >= cfg.adx_trend_min:
        market = "trend"
    elif adx_val < cfg.adx_range_max:
        market = "range"
    else:
        market = "neutral"
    ok = _regime_allows(strat_regime, adx_val, cfg)
    return f"{market}{'' if ok else '!'}"    # '!' = mismatch with strategy


def _stop_levels(pf: Portfolio) -> dict:
    """Current SL / TP / trail prices for the open position (None if flat)."""
    if not pf.position.is_open:
        return {"sl_px": None, "tp_px": None, "trail_px": None}
    entry = pf.position.avg_price
    long = pf.position.side == Side.LONG
    sl_px = tp_px = trail_px = None
    if pf.sl_pct > 0:
        sl_px = entry * (1 - pf.sl_pct / 100) if long else entry * (1 + pf.sl_pct / 100)
    if pf.tp_pct > 0:
        tp_px = entry * (1 + pf.tp_pct / 100) if long else entry * (1 - pf.tp_pct / 100)
    if pf.trail_pct > 0:
        trail_px = (pf._peak   * (1 - pf.trail_pct / 100) if long
                    else pf._trough * (1 + pf.trail_pct / 100))
    return {"sl_px": sl_px, "tp_px": tp_px, "trail_px": trail_px}


def run_backtest(bars: List[Bar], strat: Strategy, cfg: RunConfig) -> Portfolio:
    pf = Portfolio(
        cfg.capital,
        fee_bps=cfg.fee_bps, slippage_bps=cfg.slippage_bps,
        sl_pct=cfg.sl_pct, tp_pct=cfg.tp_pct, trail_pct=cfg.trail_pct,
        leverage=cfg.leverage,
    )
    strat.on_start()

    adx_active = (cfg.adx_filter
                  or cfg.adx_exit_on_flip
                  or cfg.adx_tighten_trail_on_flip > 0
                  or cfg.record_diagnostics)
    adx = ADX(cfg.adx_len) if adx_active else None
    strat_regime = getattr(strat, "regime", "any")
    base_trail = pf.trail_pct
    trail_tightened = False

    for bar in bars:
        adx_val = adx.update(bar) if adx is not None else None
        regime_ok = _regime_allows(strat_regime, adx_val, cfg)

        # ---- regime-aware exits (only while a position is open) ----
        if pf.position.is_open and strat_regime != "any" and adx_val is not None:
            if not regime_ok:
                if cfg.adx_exit_on_flip:
                    pf._close(bar, tag="regime_flip")
                    if cfg.record_diagnostics:
                        _log_diag(pf, bar, adx_val, strat_regime, cfg, closed_by="regime_flip")
                    continue
                if cfg.adx_tighten_trail_on_flip > 0 and not trail_tightened:
                    pf.trail_pct = cfg.adx_tighten_trail_on_flip
                    trail_tightened = True
            elif trail_tightened:
                pf.trail_pct = base_trail
                trail_tightened = False

        ctx = StrategyContext(pf.position, pf.equity(bar.close), pf.cash)
        sig = strat.on_bar(bar, ctx)

        if (cfg.adx_filter
                and sig in (Signal.BUY, Signal.SELL)
                and pf.position.qty == 0
                and not regime_ok):
            sig = Signal.HOLD

        pf.handle_signal(sig, bar, qty_pct=cfg.qty_pct)

        if not pf.position.is_open and trail_tightened:
            pf.trail_pct = base_trail
            trail_tightened = False

        if cfg.record_diagnostics:
            _log_diag(pf, bar, adx_val, strat_regime, cfg)

    if bars:
        pf.force_close(bars[-1])
    strat.on_stop()
    return pf


def _log_diag(pf: Portfolio, bar: Bar, adx_val, strat_regime: str,
              cfg: RunConfig, closed_by: str = "") -> None:
    """Append one diagnostics row for this bar."""
    stops = _stop_levels(pf)
    if closed_by:
        tid = pf._last_closed_trade_id
    elif pf.position.is_open:
        tid = pf._current_trade_id
    else:
        tid = None
    pf.diag.append({
        "ts": bar.ts.isoformat(),
        "trade_id": tid if tid is not None else "",
        "close": bar.close,
        "high": bar.high,
        "low": bar.low,
        "adx": adx_val,
        "regime": _regime_label(strat_regime, adx_val, cfg),
        "strat_regime": strat_regime,
        "trend_min": cfg.adx_trend_min,
        "range_max": cfg.adx_range_max,
        "position_side": (pf.position.side.value if pf.position.is_open else "flat"),
        "position_qty": pf.position.qty,
        "entry_price": pf.position.avg_price if pf.position.is_open else None,
        "peak": pf._peak if pf.position.is_open else None,
        "trough": pf._trough if pf.position.is_open else None,
        "sl_px": stops["sl_px"],
        "tp_px": stops["tp_px"],
        "trail_px": stops["trail_px"],
        "trail_pct_active": pf.trail_pct,
        "closed_by": closed_by,
    })


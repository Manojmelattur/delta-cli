"""Scheduler loop — `python -m delta_bt watch`.

Every ~15 s: read `deployments WHERE status='running'`, and for any row whose
`last_tick_at` is older than `interval_sec`, replay its strategy over recent
candles and place an order on the deployment's venue when the last bar signals
BUY or SELL. Errors are captured per-deployment and never break the loop.

Same behavior whether launched locally, from Docker, or manually.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone 
from typing import Any, Dict, Optional

from .core.registry import load_strategy
from .core.strategy import StrategyContext
from .core.types import Position, Signal
from .data.delta_client import DeltaClient
from .data.history import load_history
from .deployments import (
    add_realized, get_deployment, list_deployments, open_db,
    record_event, record_event_full, set_open_position, set_prior_signal,
    set_status, update_tick,
    scheduler_heartbeat, consume_scheduler_restart,
    scheduler_log,
)


# Mirror every print() into the scheduler_logs table so the web UI can tail it.
_real_print = print
def print(*args, **kwargs):  # type: ignore[override]
    try:
        msg = " ".join(str(a) for a in args)
        # naive level inference from bracketed prefixes like [warn] / [error]
        low = msg.lower()
        if "traceback" in low or "error" in low or "exception" in low:
            lvl = "ERROR"
        elif "warn" in low:
            lvl = "WARN"
        else:
            lvl = "INFO"
        scheduler_log(msg, level=lvl)
    except Exception:
        pass
    return _real_print(*args, **kwargs)


STEP_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400, "7d": 604800,
}

BASE_LIVE = os.getenv("DELTA_LIVE_BASE_URL", "https://api.india.delta.exchange")
BASE_TESTNET = os.getenv("DELTA_TESTNET_BASE_URL", "https://testnet-api.delta.exchange")

# Safety net: if mark price has slipped past the computed SL by more than this
# percent of entry (e.g. because the scheduler was down / restarting), force-close
# at market and log a distinct `sl_slippage` event instead of `sl_hit`.
MAX_SL_SLIPPAGE_PCT = float(os.getenv("MAX_SL_SLIPPAGE_PCT", "1.0"))


def _row_leverage(row) -> float:
    """Effective leverage divisor (>=1) for converting stored UPNL% → price%."""
    try:
        v2 = row["risk_semantics_v2"] if isinstance(row, dict) else row["risk_semantics_v2"]
        if v2 is not None and int(v2) == 0:
            return 1.0
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    try:
        v = float(row["leverage"] or 1)
    except (IndexError, KeyError, TypeError, ValueError):
        v = 1.0
    return v if v and v > 1.0 else 1.0


def _client_for(venue: str) -> DeltaClient:
    live = venue == "live"
    base = BASE_LIVE if live else BASE_TESTNET
    prefix = "DELTA_LIVE" if live else "DELTA_TESTNET"
    key = os.getenv(f"{prefix}_API_KEY", "") or os.getenv("DELTA_API_KEY", "")
    sec = os.getenv(f"{prefix}_API_SECRET", "") or os.getenv("DELTA_API_SECRET", "")
    return DeltaClient(base, key, sec)


def _needs_tick(row) -> bool:
    interval = int(row["interval_sec"] or 300)
    last = row["last_tick_at"]
    if not last:
        return True
    try:
        prev = datetime.fromisoformat(last)
    except ValueError:
        return True
    if prev.tzinfo is None:
        prev = prev.replace(tzinfo=timezone.utc)
    return (datetime.now(tz=timezone.utc) - prev).total_seconds() >= interval


TAIL_ONLY_STRATEGIES = {
    "price_action_pinbar", "price_action_engulfing",
    "fvg", "smc_ob", "smc_ob_fvg", "smc_liquidity_sweep",
    "macd_divergence", "rsi_divergence",
    "bollinger", "rsi_mr", "vwap",
}

# Trend strategies use a wide tail so late-starting bots can still catch a flip
# without entering mid-move. Range / tail-only strategies use a tighter,
# resolution-scaled tail so slow timeframes (1h+) don't blackout when a
# scheduler tick lands one bar after the cross.
_TAIL_BY_RES = {
    "1m": 1, "3m": 1, "5m": 1,
    "15m": 1, "30m": 1,
    "1h": 1, "2h": 1,
    "4h": 1, "6h": 1,
    "1d": 1, "7d": 1,
}
_RANGE_TAIL_BY_RES = {
    "1m": 1, "3m": 1, "5m": 1,
    "15m": 1, "30m": 1,
    "1h": 1, "2h": 1,
    "4h": 1, "6h": 1,
    "1d": 1, "7d": 1,
}


def _evaluate(row):
    """Return (signal_name, last_close, reason).

    reason values (for the throttled `evaluation` event):
      signal_fresh          — BUY/SELL inside tail window (will fire)
      signal_replay         — BUY/SELL older than tail, trend strategy fallback
      flat_exit             — strategy asked to close (FLAT)
      tail_window_expired   — had a BUY/SELL in replay but outside tail window
      no_signal             — strategy produced no BUY/SELL anywhere in replay

    Staleness is prevented by tightening the tail window to 1 bar for
    range / tail-only strategies (so Bollinger, RSI_MR, pinbar etc. only
    enter when the pattern is on the last closed bar). Trend strategies
    are edge-triggered and keep the wider auto-scaled tail as a rescue
    window so late-starting bots can still catch a flip.
    """
    strat = load_strategy(row["strategy"], json.loads(dict(row).get("params_json") or "{}"))
    if hasattr(strat, "on_start"):
        strat.on_start()
    step = STEP_SECONDS.get(row["resolution"], 900)
    end = datetime.now(tz=timezone.utc) - timedelta(seconds=30)
    start = end - timedelta(seconds=step * 400)

    # Testnet Data Proxy: if trading a USDT testnet perp, proxy the candles from
    # its live USD equivalent (e.g. BTCUSD -> BTCUSD) so it gets real volume.
    history_symbol = row["symbol"]
    history_venue = row["venue"]
    # if history_venue == "testnet" and history_symbol.endswith("USDT"):
    #     history_symbol = history_symbol[:-1]
    #     history_venue = "live"

    client = _client_for(history_venue if history_venue not in ("paper","paper_live") else "live")
    bars = load_history(client, history_symbol, row["resolution"], start, end)
    if len(bars) < 2:
        raise RuntimeError("not enough bars")
    pos = Position(symbol=row["symbol"])
    strat_regime = getattr(strat, "regime", None) or getattr(type(strat), "regime", "any")
    tail_only = strat_regime == "range" or row["strategy"] in TAIL_ONLY_STRATEGIES
    tail = (_RANGE_TAIL_BY_RES.get(row["resolution"], 1) if tail_only
            else _TAIL_BY_RES.get(row["resolution"], 3))
    tail_sig = None
    latest_sig = None
    # Fetch ticker for alpha data once
    fr = 0.0
    oi = 0.0
    try:
        if hasattr(client, 'tickers'):
            ticker = client.tickers(history_symbol)
            if isinstance(ticker, list) and len(ticker) > 0:
                t = ticker[0]
                fr = float(t.get("funding_rate", 0) or 0)
                oi = float(t.get("open_interest", 0) or 0)
            elif isinstance(ticker, dict):
                fr = float(ticker.get("funding_rate", 0) or 0)
                oi = float(ticker.get("open_interest", 0) or 0)
    except Exception:
        pass
        
    last_sig = "HOLD"
    n = len(bars)
    for i, bar in enumerate(bars):
        # We only pass the latest alpha data to all bars in this batch evaluation.
        # Historical alpha data is not easily available, so we use current for the entire lookback.
        sig = strat.on_bar(bar, StrategyContext(pos, 0.0, 0.0, funding_rate=fr, open_interest=oi))
        name = sig.name if hasattr(sig, "name") else str(sig)
        last_sig = name
        if name in ("BUY", "SELL"):
            latest_sig = name
            if i >= n - tail:
                tail_sig = name
    if hasattr(strat, "on_stop"):
        strat.on_stop()
    last_close = float(bars[-1].close)

    # Range/tail-only strategies: if no fresh tail signal, ask the strategy
    # for its current intent given the last bar. Closes the blackout where
    # the cross fired outside the tail window but the setup is still valid.
    intent_sig = None
    if tail_only and not tail_sig and hasattr(strat, "intent"):
        try:
            raw = strat.intent(bars[-1])
            raw_name = raw.name if hasattr(raw, "name") else (str(raw) if raw else None)
            if raw_name in ("BUY", "SELL"):
                intent_sig = raw_name
        except Exception:
            pass

    if last_sig == "FLAT":
        return "FLAT", last_close, "flat_exit"
    if tail_sig:
        return tail_sig, last_close, "signal_fresh"
    if intent_sig:
        return intent_sig, last_close, "signal_intent"
    if latest_sig and not tail_only:
        return latest_sig, last_close, "signal_replay"
    if latest_sig and tail_only:
        return "HOLD", last_close, "tail_window_expired"
    return last_sig, last_close, "no_signal"




def _latest_mark(row, fallback: float) -> float:
    """Use the live ticker mark for risk exits.

    Strategy signals still come from candle replay, but SL/TP/trailing must not
    wait for the next candle close. If BTC hits TP or retraces through the
    trailing stop inside the candle, the scheduler should close on that tick.
    """
    if row["venue"] == "paper":
        return fallback
    try:
        venue = "live" if row["venue"] == "paper_live" else row["venue"]
        t = _client_for(venue).ticker(row["symbol"])
        mark = float(t.get("mark_price") or t.get("close") or 0)
        return mark if mark > 0 else fallback
    except Exception:
        return fallback


def _place(row, side: str, size: float, *, reduce_only: bool = False, mark: Optional[float] = None) -> Dict[str, Any]:
    if row["venue"] in ("paper","paper_live"):
        return {"paper": True, "side": side, "size": size}
    if row["venue"] == "live" and not row["i_understand_live"]:
        raise RuntimeError("live deployment missing i_understand_live=1")
    client = _client_for(row["venue"])
    prod = client.get_product(row["symbol"])
    
    import json
    params = json.loads(dict(row).get("params_json") or "{}")
    
    order_type = "market_order"
    limit_price = None
    time_in_force = "gtc"
    post_only = False
    
    if params.get("use_limit", False) and mark is not None:
        order_type = "limit_order"
        time_in_force = "ioc" # Immediate or Cancel - if it doesn't fill, we retry next tick
        post_only = True
        
        # Calculate limit price at the bid/ask
        # If buying, limit price is the current mark (or best bid if we had orderbook, but mark is close)
        # If selling, limit price is the current mark
        tick_size = float(prod.get("tick_size", "0.01"))
        if side == "buy":
            limit_price = str(round(mark - tick_size, 8))
        else:
            limit_price = str(round(mark + tick_size, 8))

    try:
        return client.place_order(
            int(prod["id"]), int(max(1, round(size))), side,
            order_type=order_type, reduce_only=reduce_only,
            limit_price=limit_price, time_in_force=time_in_force, post_only=post_only
        )
    except Exception as e:
        if "post_only" in str(e).lower() or "ioc" in str(e).lower():
            # If the IOC/post-only is rejected by the exchange, fallback to market order
            return client.place_order(
                int(prod["id"]), int(max(1, round(size))), side,
                order_type="market_order", reduce_only=reduce_only,
            )
        raise


# ---------------------------------------------------------------------------
# Exchange-side bracket orders (Delta reduce-only stops mirroring app SL/TP).
# ---------------------------------------------------------------------------
_SL_RATCHET_MIN_PCT = 0.05  # ignore SL moves < 0.05% of entry


def _trigger_for(open_side: str, order_type: str) -> str:
    """Derive Delta stop `trigger` direction from position side + kind.

    Long  (exit sell) SL → "below"   TP → "above"
    Short (exit buy)  SL → "above"   TP → "below"
    Delta defaults to "above" when omitted, which silently inverts a
    long-position SL (order never fires on a downside move).
    """
    if open_side == "buy":
        return "below" if order_type == "stop_loss_order" else "above"
    return "above" if order_type == "stop_loss_order" else "below"

def _round_price(px: float, tick_size: str) -> float:
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(px)).quantize(Decimal(str(tick_size)), rounding=ROUND_HALF_UP))

def _check_exchange_sync(row) -> bool:
    """Return True if the exchange has no position but we think we do."""
    if row["venue"] not in ("live", "testnet"):
        return False
    if not row["open_side"] or not row["open_qty"]:
        return False
    try:
        client = _client_for(row["venue"])
        positions = client.positions()
        pos = next((p for p in positions if p.get("product_symbol") == row["symbol"]), None)
        size = float(pos.get("size", 0)) if pos else 0.0
        if size == 0:
            return True
    except Exception:
        pass
    return False

def _brackets_enabled(row) -> bool:
    if row["venue"] not in ("live", "testnet"):
        return False
    try:
        return int(row["exchange_brackets"] or 0) == 1
    except (IndexError, KeyError):
        return True  # default on for legacy rows


def _set_brackets(dep_id: int, sl_id: Optional[int], tp_id: Optional[int],
                  sl_px: Optional[float], tp_px: Optional[float]) -> None:
    from .deployments import open_db
    with open_db() as c:
        c.execute(
            "UPDATE deployments SET sl_order_id=?, tp_order_id=?, sl_stop_price=?, tp_stop_price=? WHERE id=?",
            (sl_id, tp_id, sl_px, tp_px, dep_id),
        )


def _place_brackets(row, entry_fill: float) -> None:
    if not _brackets_enabled(row):
        return
    open_side = row["open_side"]; qty = float(row["open_qty"] or 0)
    if not open_side or not qty:
        return
    exit_side = "sell" if open_side == "buy" else "buy"
    lev = _row_leverage(row)
    sl_pct = float(row["sl_pct"] or 0) / lev
    tp_pct = float(row["tp_pct"] or 0) / lev
    sl_px = (entry_fill * (1 - sl_pct/100) if open_side == "buy" else entry_fill * (1 + sl_pct/100)) if sl_pct else None
    tp_px = (entry_fill * (1 + tp_pct/100) if open_side == "buy" else entry_fill * (1 - tp_pct/100)) if tp_pct else None
    try:
        client = _client_for(row["venue"])
        prod = client.get_product(row["symbol"])
        pid = int(prod["id"])
        tick_size = prod.get("tick_size", "0.01")
        if sl_px: sl_px = _round_price(sl_px, tick_size)
        if tp_px: tp_px = _round_price(tp_px, tick_size)
        sl_id = tp_id = None
        if sl_px:
            o = client.place_stop_order(pid, int(max(1, round(qty))), exit_side, sl_px,
                                        "stop_loss_order", _trigger_for(open_side, "stop_loss_order"))
            sl_id = int(o.get("id")) if isinstance(o, dict) and o.get("id") else None
        if tp_px:
            o = client.place_stop_order(pid, int(max(1, round(qty))), exit_side, tp_px,
                                        "take_profit_order", _trigger_for(open_side, "take_profit_order"))
            tp_id = int(o.get("id")) if isinstance(o, dict) and o.get("id") else None
        _set_brackets(row["id"], sl_id, tp_id, sl_px, tp_px)
        record_event_full(row["id"], "brackets_placed",
                          message=f"brackets placed sl={sl_px} tp={tp_px}",
                          sl=sl_px, tp=tp_px)
    except Exception as e:  # noqa: BLE001
        record_event_full(row["id"], "bracket_error", message=f"bracket place failed: {e}")


def _cancel_brackets(row) -> None:
    if row["venue"] not in ("live", "testnet"):
        return
    ids = []
    try:
        if row["sl_order_id"]: ids.append(int(row["sl_order_id"]))
        if row["tp_order_id"]: ids.append(int(row["tp_order_id"]))
    except (IndexError, KeyError):
        return
    if not ids:
        return
    try:
        client = _client_for(row["venue"])
        pid = int(client.get_product(row["symbol"])["id"])
        for oid in ids:
            try: client.cancel_order(pid, oid)
            except Exception: pass
    except Exception:
        pass
    _set_brackets(row["id"], None, None, None, None)


def _sync_sl_bracket(row, new_sl_px: Optional[float]) -> None:
    if not _brackets_enabled(row) or new_sl_px is None:
        return
    open_side = row["open_side"]; qty = float(row["open_qty"] or 0)
    entry = float(row["open_price"] or 0)
    if not open_side or not qty or not entry:
        return
    try:
        prev = row["sl_stop_price"]
        prev = float(prev) if prev is not None else None
    except (IndexError, KeyError):
        prev = None
    if prev is not None:
        if abs(new_sl_px - prev) / entry * 100 < _SL_RATCHET_MIN_PCT: return
        if open_side == "buy" and new_sl_px <= prev: return
        if open_side == "sell" and new_sl_px >= prev: return
    exit_side = "sell" if open_side == "buy" else "buy"
    try:
        client = _client_for(row["venue"])
        prod = client.get_product(row["symbol"])
        pid = int(prod["id"])
        tick_size = prod.get("tick_size", "0.01")
        new_sl_px = _round_price(new_sl_px, tick_size)
        try:
            if row["sl_order_id"]:
                try: client.cancel_order(pid, int(row["sl_order_id"]))
                except Exception: pass
        except (IndexError, KeyError):
            pass
        o = client.place_stop_order(pid, int(max(1, round(qty))), exit_side, new_sl_px,
                                    "stop_loss_order", _trigger_for(open_side, "stop_loss_order"))
        new_id = int(o.get("id")) if isinstance(o, dict) and o.get("id") else None
        tp_id = None
        tp_px = None
        try:
            tp_id = int(row["tp_order_id"]) if row["tp_order_id"] else None
            tp_px = float(row["tp_stop_price"]) if row["tp_stop_price"] is not None else None
        except (IndexError, KeyError): pass
        _set_brackets(row["id"], new_id, tp_id, new_sl_px, tp_px)
        record_event_full(row["id"], "bracket_sync",
                          message=f"sl bracket {prev} → {new_sl_px}", sl=new_sl_px)
    except Exception as e:  # noqa: BLE001
        record_event_full(row["id"], "bracket_error", message=f"bracket sync failed: {e}")



# Cache Delta contract multipliers per (venue, symbol). ETHUSD = 0.01 ETH per
# contract, BTCUSD = 0.001 BTC per contract, etc. Realized PnL in USD MUST
# multiply by this to match what Delta reports on the exchange fills page.
_CV_CACHE: Dict[str, float] = {}


def _contract_value(row) -> float:
    venue = row["venue"]
    lookup = "live" if venue in ("paper", "paper_live") else venue
    symbol = row["symbol"]
    key = f"{lookup}:{symbol}"
    if key in _CV_CACHE:
        return _CV_CACHE[key]
    try:
        prod = _client_for(lookup).get_product(symbol)
        cv = float(prod.get("contract_value") or 1) or 1.0
    except Exception:
        cv = 1.0
    _CV_CACHE[key] = cv
    return cv


def _asset_symbol(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("symbol") or "").upper()
    if value:
        return str(value).upper()
    return ""


# _STABLE_EQUIVS = {
#     "USD": ["USD", "USDT", "USDC"],
#     "USDT": ["USDT", "USD", "USDC"],
#     "USDC": ["USDC", "USD", "USDT"],
# }


def _margin_asset_candidates(prod: dict) -> list:
    primary = [
        _asset_symbol(prod.get("settlement_asset")),
        _asset_symbol(prod.get("quoting_asset")),
    ]
    return  [a for a in primary if a] or ["USD"]
    # out: list = []
    # for a in primary:
    #     for eq in _STABLE_EQUIVS.get(a, [a]):
    #         if eq not in out:
    #             out.append(eq)
    # return out or ["USD", "USDT", "USDC"]


def _entry_margin_preflight(row, side: str, size: float, mark: float) -> None:
    """Block obviously unaffordable live/testnet entries before Delta rejects them.

    Delta `size` = number of lots. Required margin:
      notional = lots × contract_value × price
      required = max(notional/leverage, notional × initial_margin_pct/100)
    """
    if row["venue"] not in ("live", "testnet"):
        return
    try:
        if int(row["reduce_only"] or 0) == 1:
            return
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    client = _client_for(row["venue"])
    prod = client.get_product(row["symbol"])
    cv = float(prod.get("contract_value") or 1) or 1.0
    lev = max(1.0, _row_leverage(row))
    min_pct = 0.0
    try:
        min_pct = max(0.0, float(prod.get("initial_margin") or 0))
    except (TypeError, ValueError):
        min_pct = 0.0
    notional = abs(size) * float(mark) * cv
    required = max(notional / lev, notional * (min_pct / 100.0))
    buffer = max(0.05, required * 0.02)
    try:
        balances = client.balances()
    except Exception as e:
        msg = f"entry blocked: margin_unknown — wallet balance unavailable for {row['symbol']}: {e}"
        record_event_full(row["id"], "entry_blocked", message=msg, side=side, qty=size, price=mark)
        raise RuntimeError(msg)
    preferred = _margin_asset_candidates(prod)
    by_asset = {str(b.get("asset_symbol", "")).upper(): b for b in balances}
    bal = next((by_asset[a] for a in preferred if a in by_asset), None)
    available = float((bal or {}).get("available_balance") or 0)
    asset = str((bal or {}).get("asset_symbol") or (preferred[0] if preferred else "margin"))
    needed = required + buffer
    if available + 1e-9 >= needed:
        return
    missing = max(0.0, needed - available)
    msg = (
        f"entry blocked: insufficient_margin_preflight — {size:g} lot(s) {row['symbol']} @ {mark:.4f} "
        f"({lev:g}x · min {min_pct}% · notional {notional:.4f}). "
        f"Need ≈{needed:.4f} {asset}, available {available:.4f} {asset}. Missing ≈{missing:.4f} {asset}."
    )
    record_event_full(row["id"], "entry_blocked", message=msg, side=side, qty=size, price=mark)
    raise RuntimeError(msg)



def _pnl(open_side: str, open_price: float, close_price: float, qty: float, cv: float = 1.0) -> float:
    if open_side == "buy":
        return (close_price - open_price) * qty * cv
    return (open_price - close_price) * qty * cv


def _check_risk_exit(row, mark: float) -> Optional[str]:
    """Return 'sl_hit' | 'tp_hit' | 'trail_hit' | None for an open position vs mark.

    Honors dynamic profit-activated trail:
      - trail fires only after trail_armed = 1 (unrealized profit >= trail_activate_pct)
      - once be_armed = 1 (profit >= breakeven_after_pct), SL cannot be worse than entry
    Uses current ticker mark supplied by _latest_mark, not only candle close.
    """
    side = row["open_side"]; entry = row["open_price"]
    if not side or not entry:
        return None
    entry = float(entry)
    lev = _row_leverage(row)
    sl = float(row["sl_pct"] or 0) / lev
    tp = float(row["tp_pct"] or 0) / lev
    trail = float(row["trail_pct"] or 0) / lev
    # New columns default to 0 on legacy rows.
    try:
        trail_armed = int(row["trail_armed"] or 0)
        be_armed = int(row["be_armed"] or 0)
        peak = row["peak_price"]
        trough = row["trough_price"]
    except (IndexError, KeyError):
        trail_armed = 0; be_armed = 0; peak = None; trough = None

    if side == "buy":
        sl_px = entry * (1 - sl / 100.0) if sl else None
        if be_armed:
            sl_px = entry if sl_px is None else max(sl_px, entry)
        if trail and trail_armed:
            base = float(peak) if peak is not None else entry
            trail_px = base * (1 - trail / 100.0)
            sl_px = trail_px if sl_px is None else max(sl_px, trail_px)
        if sl_px is not None and mark <= sl_px:
            slip = (sl_px - mark) / entry * 100.0
            return "sl_slippage" if slip > MAX_SL_SLIPPAGE_PCT else "sl_hit"
        if tp and mark >= entry * (1 + tp / 100.0): return "tp_hit"
    else:
        sl_px = entry * (1 + sl / 100.0) if sl else None
        if be_armed:
            sl_px = entry if sl_px is None else min(sl_px, entry)
        if trail and trail_armed:
            base = float(trough) if trough is not None else entry
            trail_px = base * (1 + trail / 100.0)
            sl_px = trail_px if sl_px is None else min(sl_px, trail_px)
        if sl_px is not None and mark >= sl_px:
            slip = (mark - sl_px) / entry * 100.0
            return "sl_slippage" if slip > MAX_SL_SLIPPAGE_PCT else "sl_hit"
        if tp and mark <= entry * (1 - tp / 100.0): return "tp_hit"
    return None


def _close_position(row, exit_price: float, reason: str) -> None:
    """Emit exit event + update realized_pnl + clear open position."""
    open_side = row["open_side"]; open_qty = float(row["open_qty"] or 0)
    open_price = float(row["open_price"] or 0)
    if not open_side or not open_qty:
        return
    exit_side = "sell" if open_side == "buy" else "buy"
    # Cancel Delta-side brackets first so they don't fire against a flat pos.
    _cancel_brackets(row)
    pnl = _pnl(open_side, open_price, exit_price, open_qty, _contract_value(row))
    order_id = ""
    try:
        if row["venue"] not in ("paper","paper_live"):
            res = _place(row, exit_side, open_qty, reduce_only=True, mark=exit_price)
            order_id = str(res.get("id", "")) if isinstance(res, dict) else ""
    except Exception as e:  # noqa: BLE001
        err = str(e)
        # Delta says the position no longer exists (manually closed, liquidated,
        # or filled elsewhere). Clear local state so we stop looping every tick
        # and can re-enter on the next signal.
        if "no_position_for_user" in err or "no_position_for_reduce_only" in err or "no position" in err.lower():
            record_event_full(row["id"], "close",
                              message=f"exchange has no position — clearing local state ({err})",
                              side=exit_side, qty=open_qty, price=exit_price)
            set_open_position(row["id"], None, None, None)
            return
        record_event_full(row["id"], "error",
                          message=f"exit order failed: {err}",
                          side=exit_side, qty=open_qty, price=exit_price)
        return
    add_realized(row["id"], pnl)
    record_event_full(
        row["id"], reason,
        message=f"exit {open_side} {open_qty} @ {exit_price:.4f} (pnl {pnl:.4f})",
        order_id=order_id, pnl=pnl,
        side=exit_side, qty=open_qty, price=exit_price,
        sl=row["sl_pct"], tp=row["tp_pct"], trail=row["trail_pct"],
        peak=row["peak_price"] if "peak_price" in row.keys() else None,
        trough=row["trough_price"] if "trough_price" in row.keys() else None,
        sl_px=row["last_sl_px"] if "last_sl_px" in row.keys() else None,
    )
    set_open_position(row["id"], None, None, None)


def _open_position(row, side: str, mark: float) -> None:
    size = float(row["size"])
    
    # Check for Kelly Criterion override in params
    import json
    params = json.loads(dict(row).get("params_json") or "{}")
    if params.get("use_kelly", False):
        try:
            # Fetch past trades to compute Kelly
            from delta_bt.store.db import connect
            with connect() as cconn:
                trades = cconn.execute(
                    "SELECT pnl FROM deployment_events WHERE deployment_id=? AND pnl IS NOT NULL", 
                    (row["id"],)
                ).fetchall()
            
            wins = [float(t[0]) for t in trades if float(t[0]) > 0]
            losses = [abs(float(t[0])) for t in trades if float(t[0]) < 0]
            
            if len(wins) > 0 and len(losses) > 0 and len(trades) >= 10:
                w = len(wins) / len(trades)
                avg_win = sum(wins) / len(wins)
                avg_loss = sum(losses) / len(losses)
                r = avg_win / avg_loss if avg_loss > 0 else 1.0
                
                kelly_pct = w - ((1 - w) / r)
                # Half-kelly for safety, capped at 5x base size
                if kelly_pct > 0:
                    safe_kelly = min(kelly_pct / 2.0, 0.5) 
                    # Assuming base size represents 10% of capital, scale it
                    new_size = max(1, round(size * (safe_kelly / 0.1)))
                    record_event_full(row["id"], "kelly_sizing", message=f"Kelly scaled size {size} -> {new_size} (K={kelly_pct:.2f})")
                    size = new_size
        except Exception:
            pass
    # Sync leverage to Delta before entry (live/testnet only).
    try:
        want_sync = int(row["sync_leverage"] if "sync_leverage" in row.keys() else 1) == 1
    except (IndexError, KeyError, TypeError, ValueError):
        want_sync = True
    if want_sync and row["venue"] in ("live", "testnet"):
        try:
            lv = float(row["leverage"] or 1)
        except (IndexError, KeyError, TypeError, ValueError):
            lv = 1.0
        if lv >= 1.0:
            try:
                client = _client_for(row["venue"])
                pid = int(client.get_product(row["symbol"])["id"])
                client.set_leverage(pid, lv)
                record_event_full(row["id"], "leverage_synced",
                                  message=f"leverage synced to Delta: {lv}x")
            except Exception as e:  # noqa: BLE001
                msg = str(e).lower()
                soft = ("position" in msg or "no_change" in msg or "same" in msg or "already" in msg)
                if soft:
                    record_event_full(row["id"], "leverage_skipped",
                                      message=f"leverage sync skipped: {e}")
                else:
                    record_event_full(row["id"], "leverage_error",
                                      message=f"leverage sync failed, aborting entry: {e}",
                                      side=side, qty=size, price=mark)
                    raise
    _entry_margin_preflight(row, side, size, mark)
    order_id = ""
    try:
        res = _place(row, side, size, reduce_only=bool(row["reduce_only"]), mark=mark)
        order_id = str(res.get("id", "")) if isinstance(res, dict) else ""
    except Exception as e:  # noqa: BLE001
        record_event_full(row["id"], "error",
                          message=f"entry order failed: {e}",
                          side=side, qty=size, price=mark)
        raise
    set_open_position(row["id"], side, size, mark)
    record_event_full(
        row["id"], "entry",
        message=f"entry {side} {size} {row['symbol']} @ {mark:.4f}",
        order_id=order_id, side=side, qty=size, price=mark,
        sl=row["sl_pct"], tp=row["tp_pct"], trail=row["trail_pct"],
    )
    # Post exchange-side SL + TP brackets so protection survives scheduler
    # downtime. Paper venues are a no-op inside _place_brackets.
    _place_brackets(get_deployment(row["id"]), mark)


# Bots whose exchange-side brackets were placed by the pre-fix scheduler have
# the wrong `trigger` direction on Delta. Cancel + repost once per process so
# the direction is corrected without waiting for the trail to tighten.
_HEALED_BRACKETS: set = set()


def _heal_brackets_if_needed(row, mark: float) -> None:
    if not _brackets_enabled(row):
        return
    if not row["open_side"] or not row["open_price"]:
        return
    if not (row["sl_order_id"] or row["tp_order_id"]):
        return
    if row["id"] in _HEALED_BRACKETS:
        return
    _HEALED_BRACKETS.add(row["id"])
    try:
        _cancel_brackets(row)
        _place_brackets(get_deployment(row["id"]), float(row["open_price"]))
        record_event_full(row["id"], "brackets_healed",
                          message="reposted SL/TP with corrected trigger direction")
    except Exception as e:  # noqa: BLE001
        record_event_full(row["id"], "bracket_error", message=f"bracket heal failed: {e}")


_LAST_REASON: Dict[int, str] = {}


def _emit_evaluation(dep_id: int, sig: str, reason: str, close: float) -> None:
    """Write one `evaluation` event only when the reason changes for this bot.

    Ticks stay hidden by default in the UI; `evaluation` shows up in Activity
    and on the Bot detail page so users can see WHY a bot isn't entering
    (e.g. `tail_window_expired`, `no_signal`).
    """
    prev = _LAST_REASON.get(dep_id)
    key = f"{sig}:{reason}"
    if prev == key:
        return
    _LAST_REASON[dep_id] = key
    try:
        record_event_full(dep_id, "evaluation",
                          message=f"{reason} (signal={sig})",
                          price=close)
    except Exception:
        pass


def _tick_one(row) -> None:
    # --- Manual one-shot override -------------------------------------------
    try:
        override = row["signal_override"] if "signal_override" in row.keys() else None
    except (IndexError, KeyError):
        override = None

    if override in ("BUY", "SELL", "FLAT"):
        # Clear it immediately so it only fires once
        # db = open_db()
        # db.execute("UPDATE deployments SET signal_override=NULL WHERE id=?", (row["id"],))
        # db.commit()
        with open_db() as db:
            db.execute(
                "UPDATE deployments SET signal_override=NULL WHERE id=?",
                (row["id"],)
            )
        sig = override
        signal_mark = _latest_mark(row, 0.0)
        record_event(row["id"], "manual_override", f"Manual override applied: {override}")
        _emit_evaluation(row["id"], sig, "manual_override", signal_mark)
    else:
        try:
            sig, signal_mark, reason = _evaluate(row)
        except Exception as e:  # noqa: BLE001
            update_tick(row["id"], "ERR", err=str(e))
            record_event(row["id"], "error", str(e))
            return
        _emit_evaluation(row["id"], sig, reason, signal_mark)
    # -------------------------------------------------------------------------

    mark = _latest_mark(row, signal_mark)
    _heal_brackets_if_needed(row, mark)
    row = get_deployment(row["id"])

    # 1) Update peak/trough + trail-armed / breakeven-armed flags, then check risk exit
    if row["open_side"] and row["open_price"]:
        try:
            from .deployments import update_peak_and_arm
            update_peak_and_arm(
                row["id"], row["open_side"], float(row["open_price"]), mark,
                float(row["trail_pct"] or 0),
                float(row["trail_activate_pct"] or 0) if "trail_activate_pct" in row.keys() else 0.0,
                float(row["breakeven_after_pct"] or 0) if "breakeven_after_pct" in row.keys() else 0.0,
                float(row["sl_pct"] or 0),
            )
            row = get_deployment(row["id"])  # refresh peak/armed state
            # Mirror tightened SL to Delta as a reduce-only stop order.
            try:
                _sync_sl_bracket(row, float(row["last_sl_px"]) if row["last_sl_px"] is not None else None)
            except Exception:
                pass
        except Exception:
            pass
    reason = _check_risk_exit(row, mark)
    if not reason and _check_exchange_sync(row):
        reason = "exchange_sync_close"
        
    if reason:
        _close_position(row, mark, reason)
        row = get_deployment(row["id"])  # refresh

    # 2) unrealized PnL heartbeat
    upnl = None
    if row["open_side"] and row["open_qty"] and row["open_price"]:
        upnl = _pnl(row["open_side"], float(row["open_price"]), mark, float(row["open_qty"]), _contract_value(row))

    if sig not in ("BUY", "SELL"):
        # FLAT is an explicit "exit position" signal (e.g. rsi_mr on midline
        # cross). Close any open position; HOLD ticks stay untouched.
        if sig == "FLAT" and row["open_side"] and row["open_qty"]:
            _close_position(row, mark, "signal_exit")
        update_tick(row["id"], sig, err=None)
        record_event_full(row["id"], "tick",
                          message=f"no entry ({sig})",
                          price=mark, upnl=upnl)
        set_prior_signal(row["id"], sig)
        return

    desired = "buy" if sig == "BUY" else "sell"

    # 3) if already in the same direction, do nothing new
    if row["open_side"] == desired:
        update_tick(row["id"], sig, err=None)
        record_event_full(row["id"], "tick",
                          message=f"hold {desired} (still {sig})",
                          side=desired, price=mark, upnl=upnl)
        set_prior_signal(row["id"], sig)
        return

    # Prevent re-entry on the same signal if we got stopped out or manually closed
    try:
        prior = row["prior_signal"] if "prior_signal" in row.keys() else None
    except (IndexError, KeyError):
        prior = None
        
    if not row["open_side"] and prior == sig:
        update_tick(row["id"], "HOLD", err=None)
        # Avoid spamming events for every tick we sit flat
        return

    # 4) opposite side open: close first
    if row["open_side"] and row["open_side"] != desired:
        _close_position(row, mark, "flip")
        row = get_deployment(row["id"])

    # 5) enter new position
    try:
        _open_position(row, desired, mark)
        update_tick(row["id"], sig, err=None)
    except Exception as e:  # noqa: BLE001
        update_tick(row["id"], sig, err=str(e))
    set_prior_signal(row["id"], sig)



_running = True

def _run_background_tasks() -> None:
    from importlib import import_module
    from .store.db import list_background_tasks, log_task, connect
    try:
        tasks = list_background_tasks()
        for t in tasks:
            if t["status"] != "running": continue
            last = t["last_run_at"]
            if last:
                try: prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
                except ValueError: prev = None
                if prev and (datetime.now(tz=timezone.utc) - prev).total_seconds() < t["interval_sec"]:
                    continue
            
            # Execute
            res_val = None
            try:
                mod = import_module(f"delta_bt.tasks.{t['script_name']}")
                import json
                params = {}
                try:
                    if 'params_json' in t and t['params_json']:
                        params = json.loads(t['params_json'])
                except Exception: pass
                
                res_val = mod.run(**params)
                if res_val: log_task(t["id"], "INFO", str(res_val))
            except Exception as e:
                with connect() as conn:
                    still_exists = conn.execute(
                        "SELECT 1 FROM background_tasks WHERE id=?", (t["id"],)
                    ).fetchone()
                    if still_exists:
                        log_task(t["id"], "ERROR", f"Task failed: {e}")
            
            with connect() as conn:
                now_str = datetime.utcnow().isoformat() + "Z"
                if res_val and isinstance(res_val, str):
                    conn.execute("UPDATE background_tasks SET last_run_at=?, last_report=? WHERE id=?", 
                                 (now_str, res_val, t["id"]))
                else:
                    conn.execute("UPDATE background_tasks SET last_run_at=? WHERE id=?", 
                                 (now_str, t["id"]))
    except Exception as e:
        print(f"[watch] background tasks error: {e}", file=sys.stderr, flush=True)

def _stop(*_a) -> None:
    global _running
    _running = False

def run(interval_sec: int = 15, once: bool = False) -> int:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    print(f"[watch] scheduler started, tick every {interval_sec}s (db={os.getenv('DELTA_BT_DB','default')})",
          flush=True)
    while _running:
        try:
            scheduler_heartbeat(os.getpid(), version=os.getenv("SCHEDULER_VERSION", ""))
            reason = consume_scheduler_restart()
            if reason is not None:
                print(f"[watch] restart requested ({reason or 'no reason'}) — exiting so process manager can restart",
                      flush=True)
                sys.exit(2)
            
            # 1. Background Tasks
            _run_background_tasks()

            # 2. Deployments Tick
            rows = [r for r in list_deployments() if r["status"] == "running"]
            due = [r for r in rows if _needs_tick(r)]
            for r in due:
                print(f"[watch] tick #{r['id']} {r['name']} {r['strategy']} {r['symbol']} {r['resolution']}",
                      flush=True)
                _tick_one(r)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[watch] loop error: {e}", file=sys.stderr, flush=True)
        if once:
            return 0
        for _ in range(interval_sec):
            if not _running:
                break
            time.sleep(1)
    print("[watch] scheduler stopped", flush=True)
    return 0



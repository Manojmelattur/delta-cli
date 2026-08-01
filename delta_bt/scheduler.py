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
    set_status, update_tick, update_peak_and_arm,
    scheduler_heartbeat, consume_scheduler_restart,
    scheduler_log,
)
from .store.db import connect
 


# Mirror every print() into the scheduler_logs table so the web UI can tail it.
_real_print = print
def print(*args, **kwargs):  # type: ignore[override]
    try:
        msg = " ".join(str(a) for a in args)
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

# Fix 4: corrected testnet base URL
BASE_LIVE    = os.getenv("DELTA_LIVE_BASE_URL",    "https://api.india.delta.exchange")
BASE_TESTNET = os.getenv("DELTA_TESTNET_BASE_URL", "https://cdn-ind.testnet.deltaex.org")

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


# Fix: keep the original local _client_for in watch.py
# It correctly uses BASE_LIVE/BASE_TESTNET from env vars defined at module level.
# utils/client.py is only used by background tasks (atr_risk_manager etc.)
# Remove the import of client_for from utils and restore the original function:

def _client_for(venue: str) -> DeltaClient:
    live   = venue == "live"
    base   = BASE_LIVE if live else BASE_TESTNET
    prefix = "DELTA_LIVE" if live else "DELTA_TESTNET"
    key    = os.getenv(f"{prefix}_API_KEY", "") or os.getenv("DELTA_API_KEY", "")
    sec    = os.getenv(f"{prefix}_API_SECRET", "") or os.getenv("DELTA_API_SECRET", "")
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
    """
    strat = load_strategy(row["strategy"], json.loads(dict(row).get("params_json") or "{}"))
    if hasattr(strat, "on_start"):
        strat.on_start()
    step = STEP_SECONDS.get(row["resolution"], 900)
    end = datetime.now(tz=timezone.utc) - timedelta(seconds=30)
    start = end - timedelta(seconds=step * 400)

    history_symbol = row["symbol"]
    history_venue  = row["venue"]

    # Fix 3: paper/paper_live must use live market data, not testnet.
    # client_for() handles this correctly — passing "live" explicitly here
    # for paper venues mirrors the intent of the original guard.


    # Fix 3: paper/paper_live must use live market data
    effective_venue = "live" if history_venue in ("paper", "paper_live") else history_venue
    client = _client_for(effective_venue)

    # effective_venue = "live" if history_venue in ("paper", "paper_live") else history_venue
    # client = _client_for(effective_venue)
    bars = load_history(client, history_symbol, row["resolution"], start, end)
    if len(bars) < 2:
        raise RuntimeError("not enough bars")

    pos = Position(symbol=row["symbol"])
    strat_regime = getattr(strat, "regime", None) or getattr(type(strat), "regime", "any")
    tail_only = strat_regime == "range" or row["strategy"] in TAIL_ONLY_STRATEGIES
    tail = (_RANGE_TAIL_BY_RES.get(row["resolution"], 1) if tail_only
            else _TAIL_BY_RES.get(row["resolution"], 3))
    tail_sig   = None
    latest_sig = None

    # Fetch ticker for alpha data once
    fr = 0.0
    oi = 0.0
    try:
        if hasattr(client, "tickers"):
            ticker = client.tickers(history_symbol)
            if isinstance(ticker, list) and len(ticker) > 0:
                t = ticker[0]
                fr = float(t.get("funding_rate",  0) or 0)
                oi = float(t.get("open_interest", 0) or 0)
            elif isinstance(ticker, dict):
                fr = float(ticker.get("funding_rate",  0) or 0)
                oi = float(ticker.get("open_interest", 0) or 0)
    except Exception:
        pass

    last_sig = "HOLD"
    n = len(bars)
    for i, bar in enumerate(bars):
        sig  = strat.on_bar(bar, StrategyContext(pos, 0.0, 0.0, funding_rate=fr, open_interest=oi))
        name = sig.name if hasattr(sig, "name") else str(sig)
        last_sig = name
        if name in ("BUY", "SELL"):
            latest_sig = name
            if i >= n - tail:
                tail_sig = name

    if hasattr(strat, "on_stop"):
        strat.on_stop()
    last_close = float(bars[-1].close)

    intent_sig = None
    if tail_only and not tail_sig and hasattr(strat, "intent"):
        try:
            raw      = strat.intent(bars[-1])
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
    if row["venue"] == "paper":
        return fallback
    try:
        # Fix 3: remap both paper and paper_live to live
        venue = "live" if row["venue"] in ("paper", "paper_live") else row["venue"]
        t     = _client_for(venue).ticker(row["symbol"])
        mark  = float(t.get("mark_price") or t.get("close") or 0)
        return mark if mark > 0 else fallback
    except Exception:
        return fallback


# def _latest_mark(row, fallback: float) -> float:
#     """Use the live ticker mark for risk exits."""
#     if row["venue"] == "paper":
#         return fallback
#     try:
#         # Fix 3: remap both paper and paper_live to live so mark price
#         # is always fetched from the live feed, never from testnet.
#         venue = "live" if row["venue"] in ("paper", "paper_live") else row["venue"]
#         t     = _client_for(venue).ticker(row["symbol"])
#         mark  = float(t.get("mark_price") or t.get("close") or 0)
#         return mark if mark > 0 else fallback
#     except Exception:
#         return fallback


def _place(
    row, side: str, size: float,
    *, reduce_only: bool = False, mark: Optional[float] = None
) -> Dict[str, Any]:
    if row["venue"] in ("paper", "paper_live"):
        return {"paper": True, "side": side, "size": size}
    if row["venue"] == "live" and not row["i_understand_live"]:
        raise RuntimeError("live deployment missing i_understand_live=1")

    client = _client_for(row["venue"])
    prod   = client.get_product(row["symbol"])

    # Fix 5: removed redundant `import json` — already imported at top of file
    params = json.loads(dict(row).get("params_json") or "{}")

    order_type    = "market_order"
    limit_price   = None
    time_in_force = "gtc"
    post_only     = False

    if params.get("use_limit", False) and mark is not None:
        order_type    = "limit_order"
        time_in_force = "ioc"
        post_only     = True
        tick_size     = float(prod.get("tick_size", "0.01"))
        if side == "buy":
            limit_price = str(round(mark - tick_size, 8))
        else:
            limit_price = str(round(mark + tick_size, 8))

    try:
        return client.place_order(
            int(prod["id"]), int(max(1, round(size))), side,
            order_type=order_type, reduce_only=reduce_only,
            limit_price=limit_price, time_in_force=time_in_force, post_only=post_only,
        )
    except Exception as e:
        if "post_only" in str(e).lower() or "ioc" in str(e).lower():
            return client.place_order(
                int(prod["id"]), int(max(1, round(size))), side,
                order_type="market_order", reduce_only=reduce_only,
            )
        raise


# ---------------------------------------------------------------------------
# Exchange-side bracket orders
# ---------------------------------------------------------------------------
_SL_RATCHET_MIN_PCT = 0.05


def _trigger_for(open_side: str, order_type: str) -> str:
    """Derive Delta stop trigger direction from position side + kind.

    Long  (exit sell) SL → below   TP → above
    Short (exit buy)  SL → above   TP → below
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
        client    = _client_for(row["venue"])
        positions = client.positions()
        pos       = next((p for p in positions if p.get("product_symbol") == row["symbol"]), None)
        size      = float(pos.get("size", 0)) if pos else 0.0
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
        return True


def _set_brackets(
    dep_id: int,
    sl_id: Optional[int], tp_id: Optional[int],
    sl_px: Optional[float], tp_px: Optional[float],
) -> None:
    with open_db() as c:
        c.execute(
            "UPDATE deployments SET sl_order_id=?, tp_order_id=?, sl_stop_price=?, tp_stop_price=? WHERE id=?",
            (sl_id, tp_id, sl_px, tp_px, dep_id),
        )


def _get_risk_mode_prices(row, entry: float, peak_or_trough: Optional[float] = None) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute SL, TP, and Trailing prices based on configured risk modes (pct, atr, point)."""
    open_side = row.get("open_side") if hasattr(row, "get") else row["open_side"]
    open_side = open_side or "buy"
    lev = _row_leverage(row)
    sl_val = float((row.get("sl_pct") if hasattr(row, "get") else row["sl_pct"]) or 0)
    tp_val = float((row.get("tp_pct") if hasattr(row, "get") else row["tp_pct"]) or 0)
    trail_val = float((row.get("trail_pct") if hasattr(row, "get") else row["trail_pct"]) or 0)

    params = {}
    try:
        raw_params = (row.get("params_json") if hasattr(row, "get") else row["params_json"]) or "{}"
        params = json.loads(raw_params) if isinstance(raw_params, str) else raw_params
    except Exception:
        params = {}

    sl_type = str(params.get("sl_type", "pct")).lower()
    tp_type = str(params.get("tp_type", "pct")).lower()
    trail_type = str(params.get("trail_type", "pct")).lower()

    atr_val = None
    if "atr" in (sl_type, tp_type, trail_type):
        atr_val = params.get("atr_value") or params.get("atr")

    # SL calculation
    sl_px = None
    if sl_val > 0:
        if sl_type == "point":
            sl_dist = sl_val
        elif sl_type == "atr" and atr_val:
            sl_dist = sl_val * float(atr_val)
        else:  # pct
            sl_dist = entry * ((sl_val / lev) / 100.0)
        sl_px = entry - sl_dist if open_side == "buy" else entry + sl_dist

    # TP calculation
    tp_px = None
    if tp_val > 0:
        if tp_type == "point":
            tp_dist = tp_val
        elif tp_type == "atr" and atr_val:
            tp_dist = tp_val * float(atr_val)
        else:  # pct
            tp_dist = entry * ((tp_val / lev) / 100.0)
        tp_px = entry + tp_dist if open_side == "buy" else entry - tp_dist

    # Trail calculation
    trail_px = None
    base_px = peak_or_trough if peak_or_trough is not None else entry
    if trail_val > 0 and base_px:
        if trail_type == "point":
            trail_dist = trail_val
        elif trail_type == "atr" and atr_val:
            trail_dist = trail_val * float(atr_val)
        else:  # pct
            trail_dist = base_px * ((trail_val / lev) / 100.0)
        trail_px = base_px - trail_dist if open_side == "buy" else base_px + trail_dist

    return sl_px, tp_px, trail_px


def _place_brackets(row, entry_fill: float) -> None:
    if not _brackets_enabled(row):
        return
    open_side = row["open_side"]
    qty       = float(row["open_qty"] or 0)
    if not open_side or not qty:
        return
    exit_side = "sell" if open_side == "buy" else "buy"
    sl_px, tp_px, _ = _get_risk_mode_prices(row, entry_fill)
    try:
        client    = _client_for(row["venue"])
        prod      = client.get_product(row["symbol"])
        pid       = int(prod["id"])
        tick_size = prod.get("tick_size", "0.01")
        if sl_px:
            sl_px = _round_price(sl_px, tick_size)
        if tp_px:
            tp_px = _round_price(tp_px, tick_size)
        sl_id = tp_id = None
        if sl_px:
            o     = client.place_stop_order(pid, int(max(1, round(qty))), exit_side, sl_px,
                                            "stop_loss_order", _trigger_for(open_side, "stop_loss_order"))
            sl_id = int(o.get("id")) if isinstance(o, dict) and o.get("id") else None
        if tp_px:
            o     = client.place_stop_order(pid, int(max(1, round(qty))), exit_side, tp_px,
                                            "take_profit_order", _trigger_for(open_side, "take_profit_order"))
            tp_id = int(o.get("id")) if isinstance(o, dict) and o.get("id") else None
        _set_brackets(row["id"], sl_id, tp_id, sl_px, tp_px)
        record_event_full(row["id"], "brackets_placed",
                          message=f"brackets placed sl={sl_px} tp={tp_px}",
                          sl=sl_px, tp=tp_px)
    except Exception as e:
        record_event_full(row["id"], "bracket_error", message=f"bracket place failed: {e}")


def _cancel_brackets(row) -> None:
    if row["venue"] not in ("live", "testnet"):
        return
    ids = []
    if row["sl_order_id"]: ids.append(int(row["sl_order_id"]))
    if row["tp_order_id"]: ids.append(int(row["tp_order_id"]))
    if not ids:
        return
    try:
        client = _client_for(row["venue"])
        pid    = int(client.get_product(row["symbol"])["id"])
        for oid in ids:
            try: client.cancel_order(pid, oid)
            except Exception: pass
        _set_brackets(row["id"], None, None, None, None)
    except Exception as e:
        record_event_full(row["id"], "bracket_error", message=f"bracket cancel failed: {e}")


def _sync_sl_bracket(row, new_sl_px: Optional[float]) -> None:
    if not _brackets_enabled(row) or new_sl_px is None:
        return
    open_side = row["open_side"]
    qty       = float(row["open_qty"] or 0)
    entry     = float(row["open_price"] or 0)
    if not open_side or not qty or not entry:
        return
    try:
        prev = row["sl_stop_price"]
        prev = float(prev) if prev is not None else None
    except (IndexError, KeyError):
        prev = None
    if prev is not None:
        if abs(new_sl_px - prev) / entry * 100 < _SL_RATCHET_MIN_PCT:
            return
        if open_side == "buy"  and new_sl_px <= prev:
            return
        if open_side == "sell" and new_sl_px >= prev:
            return
    exit_side = "sell" if open_side == "buy" else "buy"
    try:
        client    = _client_for(row["venue"])
        prod      = client.get_product(row["symbol"])
        pid       = int(prod["id"])
        tick_size = prod.get("tick_size", "0.01")
        new_sl_px = _round_price(new_sl_px, tick_size)
        try:
            if row["sl_order_id"]:
                try:
                    client.cancel_order(pid, int(row["sl_order_id"]))
                except Exception:
                    pass
        except (IndexError, KeyError):
            pass
        o      = client.place_stop_order(pid, int(max(1, round(qty))), exit_side, new_sl_px,
                                         "stop_loss_order", _trigger_for(open_side, "stop_loss_order"))
        new_id = int(o.get("id")) if isinstance(o, dict) and o.get("id") else None
        tp_id  = None
        tp_px  = None
        try:
            tp_id = int(row["tp_order_id"])   if row["tp_order_id"]   else None
            tp_px = float(row["tp_stop_price"]) if row["tp_stop_price"] is not None else None
        except (IndexError, KeyError):
            pass
        _set_brackets(row["id"], new_id, tp_id, new_sl_px, tp_px)
        record_event_full(row["id"], "bracket_sync",
                          message=f"sl bracket {prev} → {new_sl_px}", sl=new_sl_px)
    except Exception as e:
        record_event_full(row["id"], "bracket_error", message=f"bracket sync failed: {e}")


# Cache Delta contract multipliers per (venue, symbol).
_CV_CACHE: Dict[str, float] = {}


def _contract_value(row) -> float:
    venue  = row["venue"]
    lookup = "live" if venue in ("paper", "paper_live") else venue
    symbol = row["symbol"]
    key    = f"{lookup}:{symbol}"
    if key in _CV_CACHE:
        return _CV_CACHE[key]
    try:
        prod = _client_for(lookup).get_product(symbol)
        cv   = float(prod.get("contract_value") or 1) or 1.0
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


def _margin_asset_candidates(prod: dict) -> list:
    primary = [
        _asset_symbol(prod.get("settlement_asset")),
        _asset_symbol(prod.get("quoting_asset")),
    ]
    return [a for a in primary if a] or ["USD"]


def _entry_margin_preflight(row, side: str, size: float, mark: float) -> None:
    """Block obviously unaffordable live/testnet entries before Delta rejects them."""
    if row["venue"] not in ("live", "testnet"):
        return
    try:
        if int(row["reduce_only"] or 0) == 1:
            return
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    client  = _client_for(row["venue"])
    prod    = client.get_product(row["symbol"])
    cv      = float(prod.get("contract_value") or 1) or 1.0
    lev     = max(1.0, _row_leverage(row))
    min_pct = 0.0
    try:
        min_pct = max(0.0, float(prod.get("initial_margin") or 0))
    except (TypeError, ValueError):
        min_pct = 0.0
    notional = abs(size) * float(mark) * cv
    required = max(notional / lev, notional * (min_pct / 100.0))
    buffer   = max(0.05, required * 0.02)
    try:
        balances = client.balances()
    except Exception as e:
        msg = (f"entry blocked: margin_unknown — wallet balance unavailable "
               f"for {row['symbol']}: {e}")
        record_event_full(row["id"], "entry_blocked", message=msg, side=side, qty=size, price=mark)
        raise RuntimeError(msg)
    preferred = _margin_asset_candidates(prod)
    by_asset  = {str(b.get("asset_symbol", "")).upper(): b for b in balances}
    bal       = next((by_asset[a] for a in preferred if a in by_asset), None)
    available = float((bal or {}).get("available_balance") or 0)
    asset     = str((bal or {}).get("asset_symbol") or (preferred[0] if preferred else "margin"))
    needed    = required + buffer
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
    """Return 'sl_hit' | 'tp_hit' | 'trail_hit' | 'tp_level_N_hit' | None for an open position vs mark."""
    side  = row["open_side"]
    entry = row["open_price"]
    if not side or not entry:
        return None

    entry = float(entry)

    # Check primary Stop Loss (computed by update_peak_and_arm)
    sl_px = row.get("last_sl_px")
    if sl_px is not None:
        sl_px = float(sl_px)
        if side == "buy" and mark <= sl_px:
            slip = (sl_px - mark) / entry * 100.0
            return "sl_slippage" if slip > MAX_SL_SLIPPAGE_PCT else "sl_hit"
        if side == "sell" and mark >= sl_px:
            slip = (mark - sl_px) / entry * 100.0
            return "sl_slippage" if slip > MAX_SL_SLIPPAGE_PCT else "sl_hit"

    # Check multi-level TPs first
    params = json.loads(dict(row).get("params_json") or "{}")
    tp_levels = params.get("tp_levels", [])
    if tp_levels:
        tp_hits = params.get("tp_hits", [])
        lev = _row_leverage(row)
        atr_val = params.get("atr_value") or params.get("atr")

        for i, level in enumerate(tp_levels):
            if i in tp_hits:
                continue

            tp_val = float(level.get("pct", 0))
            if tp_val <= 0:
                continue
                
            tp_type = str(level.get("type", "pct")).lower()
            
            if tp_type == "point":
                tp_dist = tp_val
            elif tp_type == "atr" and atr_val:
                tp_dist = tp_val * float(atr_val)
            else:  # pct
                tp_dist = entry * ((tp_val / lev) / 100.0)
                
            tp_px = entry + tp_dist if side == "buy" else entry - tp_dist
            
            if side == "buy" and mark >= tp_px:
                return f"tp_level_{i}_hit"
            if side == "sell" and mark <= tp_px:
                return f"tp_level_{i}_hit"

    # Check primary Take Profit (computed by bracket logic)
    tp_px = row.get("tp_stop_price")
    if tp_px is not None:
        tp_px = float(tp_px)
        if side == "buy" and mark >= tp_px:
            return "tp_hit"
        if side == "sell" and mark <= tp_px:
            return "tp_hit"

    return None

def _close_partial_position(row, exit_price: float, reason: str, qty_pct: float, level_idx: int) -> None:
    """Emit exit event + update realized_pnl + reduce open position."""
    open_side  = row["open_side"]
    open_qty   = float(row["open_qty"]   or 0)
    entry_qty  = float(row["size"] or open_qty)
    open_price = float(row["open_price"] or 0)
    if not open_side or not open_qty:
        return
        
    close_qty = entry_qty * (qty_pct / 100.0)
    close_qty = max(1.0, float(round(close_qty)))
    
    if close_qty >= open_qty:
        _close_position(row, exit_price, reason)
        return
        
    exit_side = "sell" if open_side == "buy" else "buy"
    pnl = _pnl(open_side, open_price, exit_price, close_qty, _contract_value(row))
    order_id = ""
    try:
        if row["venue"] not in ("paper", "paper_live"):
            res      = _place(row, exit_side, close_qty, reduce_only=True, mark=exit_price)
            order_id = str(res.get("id", "")) if isinstance(res, dict) else ""
    except Exception as e:
        err = str(e)
        if ("no_position_for_user" in err or "no_position_for_reduce_only" in err
                or "no position" in err.lower()):
            record_event_full(row["id"], "close",
                              message=f"exchange has no position — clearing local state ({err})",
                              side=exit_side, qty=close_qty, price=exit_price)
            set_open_position(row["id"], None, None, None)
            return
        record_event_full(row["id"], "error",
                          message=f"partial exit order failed: {err}",
                          side=exit_side, qty=close_qty, price=exit_price)
        return
        
    add_realized(row["id"], pnl)
    record_event_full(
        row["id"], reason,
        message=f"partial exit {open_side} {close_qty} @ {exit_price:.4f} (pnl {pnl:.4f})",
        order_id=order_id, pnl=pnl,
        side=exit_side, qty=close_qty, price=exit_price,
    )
    
    new_qty = open_qty - close_qty
    with open_db() as db:
        db.execute("UPDATE deployments SET open_qty=? WHERE id=?", (new_qty, row["id"]))
        
    _cancel_brackets(row)
    _place_brackets(get_deployment(row["id"]), open_price)


def _close_position(row, exit_price: float, reason: str) -> None:
    """Emit exit event + update realized_pnl + clear open position."""
    open_side  = row["open_side"]
    open_qty   = float(row["open_qty"]   or 0)
    open_price = float(row["open_price"] or 0)
    if not open_side or not open_qty:
        return
    exit_side = "sell" if open_side == "buy" else "buy"
    _cancel_brackets(row)
    pnl      = _pnl(open_side, open_price, exit_price, open_qty, _contract_value(row))
    order_id = ""
    try:
        if row["venue"] not in ("paper", "paper_live"):
            res      = _place(row, exit_side, open_qty, reduce_only=True, mark=exit_price)
            order_id = str(res.get("id", "")) if isinstance(res, dict) else ""
    except Exception as e:
        err = str(e)
        if ("no_position_for_user" in err or "no_position_for_reduce_only" in err
                or "no position" in err.lower()):
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
        peak=row["peak_price"]   if "peak_price"   in row.keys() else None,
        trough=row["trough_price"] if "trough_price" in row.keys() else None,
        sl_px=row["last_sl_px"]  if "last_sl_px"   in row.keys() else None,
    )
    set_open_position(row["id"], None, None, None)

    # ── One-cycle auto-stop ──────────────────────────────────────────────────
    # If this deployment was launched by the auto-scan one-cycle scanner,
    # automatically stop it after the first closed trade so it never re-enters.
    try:
        params_dict = json.loads(dict(row).get("params_json") or "{}")
        is_one_cycle = params_dict.get("one_cycle") or params_dict.get("one_shot")
    except Exception:
        is_one_cycle = False

    if is_one_cycle:
        try:
            set_status(row["id"], "stopped")
            record_event_full(
                row["id"], "one_cycle_complete",
                message=(
                    f"one-cycle trade finished ({reason}). "
                    f"Bot auto-stopped — no re-entry."
                ),
            )
            print(
                f"[watch] one-cycle #{row['id']} {row['name']} "
                f"auto-stopped after {reason}",
                flush=True,
            )
        except Exception as _e:
            pass  # never let this break the main scheduler loop


def _open_position(row, side: str, mark: float) -> None:
    size = float(row["size"])

    # Fix 5+6: removed inline `import json` and `from delta_bt.store.db import connect`
    # both are now top-level imports.
    params = json.loads(dict(row).get("params_json") or "{}")

    if params.get("use_kelly", False):
        try:
            with connect() as cconn:
                trades = cconn.execute(
                    "SELECT pnl FROM deployment_events WHERE deployment_id=? AND pnl IS NOT NULL",
                    (row["id"],)
                ).fetchall()
            wins   = [float(t[0]) for t in trades if float(t[0]) > 0]
            losses = [abs(float(t[0])) for t in trades if float(t[0]) < 0]
            if len(wins) > 0 and len(losses) > 0 and len(trades) >= 10:
                w       = len(wins) / len(trades)
                avg_win = sum(wins)   / len(wins)
                avg_loss= sum(losses) / len(losses)
                r       = avg_win / avg_loss if avg_loss > 0 else 1.0
                kelly_pct = w - ((1 - w) / r)
                if kelly_pct > 0:
                    safe_kelly = min(kelly_pct / 2.0, 0.5)
                    new_size   = max(1, round(size * (safe_kelly / 0.1)))
                    record_event_full(row["id"], "kelly_sizing",
                                      message=f"Kelly scaled size {size} -> {new_size} (K={kelly_pct:.2f})")
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
                pid    = int(client.get_product(row["symbol"])["id"])
                client.set_leverage(pid, lv)
                record_event_full(row["id"], "leverage_synced",
                                  message=f"leverage synced to Delta: {lv}x")
            except Exception as e:
                msg  = str(e).lower()
                soft = ("position" in msg or "no_change" in msg
                        or "same" in msg or "already" in msg)
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
        res      = _place(row, side, size, reduce_only=bool(row["reduce_only"]), mark=mark)
        order_id = str(res.get("id", "")) if isinstance(res, dict) else ""
    except Exception as e:
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
    _place_brackets(get_deployment(row["id"]), mark)


# Bots whose exchange-side brackets were placed by the pre-fix scheduler have
# the wrong trigger direction on Delta. Cancel + repost once per process.
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
    except Exception as e:
        record_event_full(row["id"], "bracket_error", message=f"bracket heal failed: {e}")


_LAST_REASON: Dict[int, str] = {}


def _emit_evaluation(dep_id: int, sig: str, reason: str, close: float) -> None:
    """Write one evaluation event only when the reason changes for this bot."""
    prev = _LAST_REASON.get(dep_id)
    key  = f"{sig}:{reason}"
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
        # Fix 1 (original): use `with open_db()` not bare assignment.
        # open_db() is a context manager — assigning it directly gives
        # '_GeneratorContextManager has no attribute execute'.
        with open_db() as db:
            db.execute(
                "UPDATE deployments SET signal_override=NULL WHERE id=?",
                (row["id"],)
            )
        sig         = override
        signal_mark = _latest_mark(row, 0.0)
        record_event(row["id"], "manual_override", f"Manual override applied: {override}")
        _emit_evaluation(row["id"], sig, "manual_override", signal_mark)
    else:
        try:
            sig, signal_mark, reason = _evaluate(row)
        except Exception as e:
            update_tick(row["id"], "ERR", err=str(e))
            record_event(row["id"], "error", str(e))
            return
        _emit_evaluation(row["id"], sig, reason, signal_mark)
    # -------------------------------------------------------------------------

    mark = _latest_mark(row, signal_mark)
    _heal_brackets_if_needed(row, mark)
    row = get_deployment(row["id"])

    # 1) Update peak/trough + trail-armed / breakeven-armed flags
    # Fix 7: update_peak_and_arm is now a top-level import, not inline.
    if row["open_side"] and row["open_price"]:
        try:
            update_peak_and_arm(
                row["id"], row["open_side"], float(row["open_price"]), mark,
                float(row["trail_pct"] or 0),
                float(row["trail_activate_pct"]  or 0) if "trail_activate_pct"  in row.keys() else 0.0,
                float(row["breakeven_after_pct"] or 0) if "breakeven_after_pct" in row.keys() else 0.0,
                float(row["sl_pct"] or 0),
            )
            row = get_deployment(row["id"])
            try:
                _sync_sl_bracket(
                    row,
                    float(row["last_sl_px"]) if row["last_sl_px"] is not None else None
                )
            except Exception:
                pass
        except Exception:
            pass

    reason = _check_risk_exit(row, mark)
    if not reason and _check_exchange_sync(row):
        reason = "exchange_sync_close"

    if reason:
        if reason.startswith("tp_level_"):
            level_idx = int(reason.split("_")[2])
            params = json.loads(dict(row).get("params_json") or "{}")
            tp_levels = params.get("tp_levels", [])
            tp_hits = params.get("tp_hits", [])
            
            if level_idx < len(tp_levels):
                level = tp_levels[level_idx]
                qty_pct = float(level.get("qty_pct", 100.0))
                
                if qty_pct >= 99.9:
                    _close_position(row, mark, reason)
                else:
                    _close_partial_position(row, mark, reason, qty_pct, level_idx)
                    
                tp_hits.append(level_idx)
                params["tp_hits"] = tp_hits
                with open_db() as db:
                    db.execute("UPDATE deployments SET params_json=? WHERE id=?", 
                              (json.dumps(params), row["id"]))
                
                row = get_deployment(row["id"])
        else:
            _close_position(row, mark, reason)
            row = get_deployment(row["id"])

    # 2) Unrealized PnL heartbeat
    upnl = None
    if row["open_side"] and row["open_qty"] and row["open_price"]:
        upnl = _pnl(
            row["open_side"], float(row["open_price"]), mark,
            float(row["open_qty"]), _contract_value(row)
        )

    if sig not in ("BUY", "SELL"):
        if sig == "FLAT" and row["open_side"] and row["open_qty"]:
            _close_position(row, mark, "signal_exit")
        update_tick(row["id"], sig, err=None)
        record_event_full(row["id"], "tick",
                          message=f"no entry ({sig})",
                          price=mark, upnl=upnl)
        set_prior_signal(row["id"], sig)
        return

    desired = "buy" if sig == "BUY" else "sell"

    # 3) Already in the same direction — hold
    if row["open_side"] == desired:
        update_tick(row["id"], sig, err=None)
        record_event_full(row["id"], "tick",
                          message=f"hold {desired} (still {sig})",
                          side=desired, price=mark, upnl=upnl)
        set_prior_signal(row["id"], sig)
        return

    # Prevent re-entry on the same signal after stop-out or manual close
    try:
        prior = row["prior_signal"] if "prior_signal" in row.keys() else None
    except (IndexError, KeyError):
        prior = None

    if not row["open_side"] and prior == sig:
        update_tick(row["id"], "HOLD", err=None)
        return

    # 4) Opposite side open — close first
    if row["open_side"] and row["open_side"] != desired:
        _close_position(row, mark, "flip")
        row = get_deployment(row["id"])

    # 5) Enter new position
    try:
        _open_position(row, desired, mark)
        update_tick(row["id"], sig, err=None)
    except Exception as e:
        update_tick(row["id"], sig, err=str(e))
    set_prior_signal(row["id"], sig)


_running = True


def _run_background_tasks() -> None:
    from importlib import import_module
    from .store.db import list_background_tasks, log_task

    try:
        tasks = list_background_tasks()
        for t in tasks:
            if t["status"] != "running":
                continue

            # Check if interval has elapsed since last run
            last = t["last_run_at"]
            if last:
                try:
                    prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
                except ValueError:
                    prev = None
                if prev and (datetime.now(tz=timezone.utc) - prev).total_seconds() < t["interval_sec"]:
                    continue

            # Execute task
            res_val     = None
            task_failed = False  # Fix 2: track failure so last_run_at is not updated on error

            try:
                mod    = import_module(f"delta_bt.tasks.{t['script_name'].removesuffix('.py')}")
                params = {}
                try:
                    if t.get("params_json"):
                        params = json.loads(t["params_json"])
                except Exception:
                    pass

                res_val = mod.run(**params)

                # Fix 1: guard log_task on success path with existence check
                # so a deleted task does not cause a FK error here either.
                if res_val:
                    with connect() as conn:
                        still_exists = conn.execute(
                            "SELECT 1 FROM background_tasks WHERE id=?", (t["id"],)
                        ).fetchone()
                    if still_exists:
                        log_task(t["id"], "INFO", str(res_val))

            except Exception as e:
                task_failed = True
                # Fix 1: existence check on error path prevents FK error
                # when task is deleted between list and log.
                try:
                    with connect() as conn:
                        still_exists = conn.execute(
                            "SELECT 1 FROM background_tasks WHERE id=?", (t["id"],)
                        ).fetchone()
                    if still_exists:
                        log_task(t["id"], "ERROR", f"Task failed: {e}")
                except Exception:
                    pass

            # Fix 2: only update last_run_at when task succeeded.
            # Failed tasks will retry on the next scheduler loop.
            if not task_failed:
                with connect() as conn:
                    now_str = datetime.utcnow().isoformat() + "Z"
                    if res_val and isinstance(res_val, str):
                        conn.execute(
                            "UPDATE background_tasks SET last_run_at=?, last_report=? WHERE id=?",
                            (now_str, res_val, t["id"]),
                        )
                    else:
                        conn.execute(
                            "UPDATE background_tasks SET last_run_at=? WHERE id=?",
                            (now_str, t["id"]),
                        )

    except Exception as e:
        print(f"[watch] background tasks error: {e}", file=sys.stderr, flush=True)


def _stop(*_a) -> None:
    global _running
    _running = False


def run(interval_sec: int = 15, once: bool = False) -> int:
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)
    print(
        f"[watch] scheduler started, tick every {interval_sec}s "
        f"(db={os.getenv('DELTA_BT_DB', 'default')})",
        flush=True,
    )
    while _running:
        try:
            scheduler_heartbeat(os.getpid(), version=os.getenv("SCHEDULER_VERSION", ""))
            reason = consume_scheduler_restart()
            if reason is not None:
                print(
                    f"[watch] restart requested ({reason or 'no reason'}) "
                    f"— exiting so process manager can restart",
                    flush=True,
                )
                sys.exit(2)

            # 1. Background tasks
            _run_background_tasks()

            # 2. Deployment ticks
            rows = [r for r in list_deployments() if r["status"] == "running"]
            due  = [r for r in rows if _needs_tick(r)]
            for r in due:
                print(
                    f"[watch] tick #{r['id']} {r['name']} "
                    f"{r['strategy']} {r['symbol']} {r['resolution']}",
                    flush=True,
                )
                _tick_one(r)

        except SystemExit:
            raise
        except Exception as e:
            print(f"[watch] loop error: {e}", file=sys.stderr, flush=True)

        if once:
            return 0

        for _ in range(interval_sec):
            if not _running:
                break
            time.sleep(1)

    print("[watch] scheduler stopped", flush=True)
    return 0

"""Volatility Regime Sizer Task.

Adjusts position size inversely to volatility regime:
- High volatility (ATR expanding): reduce size to maintain constant dollar risk.
- Low volatility  (ATR contracting): increase size up to a configured maximum.

Target: risk a fixed USD amount per trade regardless of market volatility.

Formula:
    target_size = max(1, round(target_risk_usd / (atr_pct * capital)))

Opt-in: set "use_vol_sizer": true in a deployment's params_json.
Runs every 4 hours (interval_sec=14400).

Per-deployment overrides (all optional, set in params_json):
    vol_atr_period      (int,   default 14)    — ATR period.
    vol_target_risk_usd (float, default 100.0) — Target risk per trade in USD.
    vol_max_size        (int,   default 10)    — Maximum allowed lot size.
    vol_min_size        (int,   default 1)     — Minimum allowed lot size.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

DEFAULT_ATR_PERIOD      = 14
DEFAULT_TARGET_RISK_USD = 100.0
DEFAULT_MAX_SIZE        = 10
DEFAULT_MIN_SIZE        = 1

_BASE_URLS = {
    "live":    "https://api.india.delta.exchange",
    "testnet": "https://cdn-ind.testnet.deltaex.org",
}
_VENUE_MAP = {
    "paper":         "live",
    "paper_live":    "live",
    "paper_testnet": "testnet",
}
_RES_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}
_CV_CACHE: dict = {}


def _client_for_venue(venue: str) -> DeltaClient:
    resolved = _VENUE_MAP.get(venue, venue)
    base_url = _BASE_URLS.get(resolved, _BASE_URLS["live"])
    return DeltaClient(base_url=base_url)


def _get_contract_value(client: DeltaClient, symbol: str) -> float:
    if symbol in _CV_CACHE:
        return _CV_CACHE[symbol]
    try:
        prod = client.get_product(symbol)
        cv   = float(prod.get("contract_value") or 1) or 1.0
    except Exception:
        cv = 1.0
    _CV_CACHE[symbol] = cv
    return cv


def _calc_atr(bars, period: int) -> Optional[float]:
    if len(bars) < period + 1:
        return None

    def _h(b): return float(b.high  if hasattr(b, "high")  else b["high"])
    def _l(b): return float(b.low   if hasattr(b, "low")   else b["low"])
    def _c(b): return float(b.close if hasattr(b, "close") else b["close"])

    trs = []
    for i in range(1, len(bars)):
        tr = max(
            _h(bars[i]) - _l(bars[i]),
            abs(_h(bars[i]) - _c(bars[i - 1])),
            abs(_l(bars[i]) - _c(bars[i - 1])),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _last_close(bars) -> float:
    b = bars[-1]
    return float(b.close if hasattr(b, "close") else b["close"])


def _fetch_bars(venue: str, symbol: str, resolution: str, period: int):
    step_sec = _RES_SECONDS.get(resolution, 3600)
    end_time = datetime.now(tz=timezone.utc)
    start    = end_time - timedelta(seconds=step_sec * period * 3)
    try:
        client = _client_for_venue(venue)
        bars   = load_history(client, symbol, resolution, start, end_time)
        return bars if bars else None
    except Exception as e:
        logger.warning(f"VolSizer: bar fetch failed for {symbol}: {e}")
        return None


def _log_event(dep_id: int, kind: str, message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat() + "Z"
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO deployment_events"
                "(deployment_id, ts, kind, message) VALUES (?, ?, ?, ?)",
                (dep_id, ts, kind, message),
            )
    except Exception as e:
        logger.warning(f"VolSizer: event log failed: {e}")


def run(**kwargs) -> str:
    """
    Volatility Regime Sizer Task.

    Kwargs:
        target_risk_usd (float, default 100.0) — Global target risk per trade.
        max_size        (int,   default 10)    — Global max lot size.
        min_size        (int,   default 1)     — Global min lot size.
        atr_period      (int,   default 14)    — Global ATR period.
        auto_apply      (bool,  default False) — Write changes to DB.
        dry_run         (bool,  default False) — Log without acting.
    """
    global_target_risk = float(kwargs.get("target_risk_usd", DEFAULT_TARGET_RISK_USD))
    global_max_size    = int(kwargs.get("max_size",           DEFAULT_MAX_SIZE))
    global_min_size    = int(kwargs.get("min_size",           DEFAULT_MIN_SIZE))
    global_atr_period  = int(kwargs.get("atr_period",         DEFAULT_ATR_PERIOD))
    auto_apply         = bool(kwargs.get("auto_apply",         False))
    dry_run            = bool(kwargs.get("dry_run",            False))

    now_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = []
    updated  = 0
    skipped  = 0

    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, symbol, resolution, venue, size, params_json "
            "FROM deployments WHERE status='running'"
        ).fetchall()

    if not rows:
        return "Volatility Regime Sizer: No running deployments found."

    for row in rows:
        dep_id     = row["id"]
        name       = row["name"]
        symbol     = row["symbol"]
        resolution = row["resolution"] or "1h"
        venue      = row["venue"]
        cur_size   = float(row["size"] or 1)

        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}

        if not params.get("use_vol_sizer", False):
            skipped += 1
            continue

        target_risk = float(params.get("vol_target_risk_usd", global_target_risk))
        max_size    = int(params.get("vol_max_size",           global_max_size))
        min_size    = int(params.get("vol_min_size",           global_min_size))
        atr_period  = int(params.get("vol_atr_period",         global_atr_period))

        bars = _fetch_bars(venue, symbol, resolution, atr_period)
        if not bars or len(bars) < atr_period + 1:
            messages.append(
                f"WARN | {name} ({symbol}): insufficient bars for ATR-{atr_period}"
            )
            continue

        atr = _calc_atr(bars, atr_period)
        if not atr or atr <= 0:
            messages.append(f"WARN | {name} ({symbol}): ATR calculation failed")
            continue

        close_px = _last_close(bars)
        if close_px <= 0:
            continue

        client = _client_for_venue(venue)
        cv     = _get_contract_value(client, symbol)

        atr_pct          = (atr / close_px) * 100.0
        risk_per_lot     = close_px * cv * (atr_pct / 100.0)
        if risk_per_lot <= 0:
            continue

        new_size = max(min_size, min(max_size, round(target_risk / risk_per_lot)))

        msg = (
            f"{name} ({symbol}): size {cur_size:.0f} -> {new_size} lots "
            f"(ATR={atr:.4f} / {atr_pct:.3f}% "
            f"risk_per_lot=${risk_per_lot:.4f} "
            f"target=${target_risk:.2f})"
        )

        if dry_run:
            messages.append(f"DRY | {msg}")
            continue

        if auto_apply and abs(new_size - cur_size) >= 1:
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET size=? WHERE id=?",
                        (new_size, dep_id),
                    )
                updated += 1
                _log_event(
                    dep_id, "vol_sizer",
                    f"Size {cur_size:.0f} -> {new_size} | {msg}",
                )
                messages.append(f"OK  | {msg} [Applied]")
            except Exception as e:
                messages.append(f"ERR | {name} ({symbol}): DB write failed — {e}")
        else:
            messages.append(f"INFO | {msg}")

    summary = (
        f"Volatility Regime Sizer complete — "
        f"updated={updated}, skipped={skipped}, "
        f"auto_apply={auto_apply}, dry_run={dry_run}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

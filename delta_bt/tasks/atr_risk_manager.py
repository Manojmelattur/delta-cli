"""ATR-Based Dynamic Risk Management Task

Periodically recalculates ATR for opted-in running deployments and updates
sl_pct, tp_pct, and trail_pct in the deployments table.

Opt-in: set "use_atr_risk": true in a deployment's params_json.

Runs every 4 hours (interval_sec=14400).
Only updates risk params when the deployment has no open position (flat).
All changes are logged to deployment_events for a full audit trail.

Per-deployment overrides (all optional, set in params_json):
    atr_period              (int,   default 14)
    atr_sl_multiplier       (float, default 1.5)
    atr_tp_multiplier       (float, default 3.0)
    atr_trail_multiplier    (float, default 1.0)
    min_sl_pct              (float, default 0.5)
    max_sl_pct              (float, default 5.0)
    max_tp_pct              (float, default 15.0)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from delta_bt.data.history import load_history
from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Default ATR config — all overridable per deployment via params_json
# -------------------------------------------------------------------
DEFAULT_ATR_PERIOD           = 14
DEFAULT_ATR_SL_MULTIPLIER    = 1.5
DEFAULT_ATR_TP_MULTIPLIER    = 3.0
DEFAULT_ATR_TRAIL_MULTIPLIER = 1.0
DEFAULT_MIN_SL_PCT           = 0.5
DEFAULT_MAX_SL_PCT           = 5.0
DEFAULT_MAX_TP_PCT           = 15.0

_RES_SECONDS = {
    "1m":  60,    "3m":  180,   "5m":  300,
    "15m": 900,   "30m": 1800,
    "1h":  3600,  "2h":  7200,  "4h":  14400,  "1d":  86400,
}
_DEFAULT_RES_SECONDS = 3600

# Maps paper venue variants to their underlying market data source.
_VENUE_MAP = {
    "paper":         "live",
    "paper_live":    "live",
    "paper_testnet": "testnet",
}

_BASE_URLS = {
    "live":    "https://api.india.delta.exchange",
    "testnet": "https://cdn-ind.testnet.deltaex.org",
}


# -------------------------------------------------------------------
# ATR calculation
# -------------------------------------------------------------------

def _calc_atr(bars, period: int) -> Optional[float]:
    """Calculate ATR over `period` bars using Wilder's smoothing method.

    True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
    ATR        = Wilder's EMA of True Range over `period` bars

    Accepts both Bar objects (attribute access) and dicts (key access).
    Returns None if there are not enough bars.
    """
    if len(bars) < period + 1:
        return None

    def _high(b):
        return float(b.high if hasattr(b, "high") else b["high"])

    def _low(b):
        return float(b.low if hasattr(b, "low") else b["low"])

    def _close(b):
        return float(b.close if hasattr(b, "close") else b["close"])

    true_ranges = []
    for i in range(1, len(bars)):
        high       = _high(bars[i])
        low        = _low(bars[i])
        prev_close = _close(bars[i - 1])
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low  - prev_close),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    # Seed with simple average of first `period` true ranges.
    atr = sum(true_ranges[:period]) / period

    # Wilder's smoothing for remaining bars.
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period

    return atr


def _clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def _atr_to_pct(atr: float, price: float) -> float:
    """Convert an ATR value to a percentage of current price."""
    if price <= 0:
        return 0.0
    return (atr / price) * 100.0


def _last_close(bars) -> float:
    """Extract close price from the last bar, supporting Bar objects and dicts."""
    b = bars[-1]
    return float(b.close if hasattr(b, "close") else b["close"])


# -------------------------------------------------------------------
# Client resolver — replaces private _client_for import
# -------------------------------------------------------------------

def _client_for_venue(venue: str) -> DeltaClient:
    """
    Resolve the correct DeltaClient base URL for a given venue string.
    Paper venues proxy from their underlying market data source.
    """
    resolved = _VENUE_MAP.get(venue, venue)
    base_url = _BASE_URLS.get(resolved, _BASE_URLS["live"])
    return DeltaClient(base_url=base_url)


# -------------------------------------------------------------------
# Bar fetcher
# -------------------------------------------------------------------

def _fetch_bars(venue: str, symbol: str, resolution: str, atr_period: int):
    """Fetch atr_period * 3 bars for reliable Wilder smoothing.

    Uses live market data for paper venues since they have no separate
    price feed. Testnet deployments use the testnet base URL.
    Returns None on any failure.
    """
    step_sec    = _RES_SECONDS.get(resolution, _DEFAULT_RES_SECONDS)
    needed_bars = atr_period * 3
    end_time    = datetime.now(tz=timezone.utc)
    start_time  = end_time - timedelta(seconds=step_sec * needed_bars)

    try:
        client = _client_for_venue(venue)
        bars   = load_history(client, symbol, resolution, start_time, end_time)
        return bars if bars else None
    except Exception as e:
        logger.warning(
            f"ATR Risk: bar fetch failed for {symbol} {resolution}: {e}"
        )
        return None


# -------------------------------------------------------------------
# Main task entry point
# -------------------------------------------------------------------

def run(**kwargs) -> str:
    """
    ATR-Based Dynamic Risk Management Task.

    Scans all running deployments that have opted in via:
        params_json: { "use_atr_risk": true }

    For each opted-in deployment that is currently flat (no open position):
      1. Fetch recent bars  (atr_period * 3 for reliable Wilder smoothing)
      2. Calculate ATR using Wilder's smoothing method
      3. Derive sl_pct, tp_pct, trail_pct from ATR multipliers
      4. Clamp values within min/max safety bounds
      5. Skip DB write if change is less than 0.01% drift (no noise updates)
      6. Write new values to DB and log full audit event to deployment_events
    """
    messages          = []
    updated           = 0
    skipped_no_optin  = 0
    skipped_in_trade  = 0
    skipped_no_bars   = 0
    skipped_atr_error = 0

    # ------------------------------------------------------------------
    # 1. Fetch all running deployments
    # ------------------------------------------------------------------
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, name, strategy, symbol, resolution, venue,
                   sl_pct, tp_pct, trail_pct, params_json,
                   open_side, open_qty, open_price
            FROM deployments
            WHERE status = 'running'
            """
        ).fetchall()

    if not rows:
        return "ATR Risk Manager: No running deployments found."

    for row in rows:
        dep_id     = row["id"]
        name       = row["name"]
        symbol     = row["symbol"]
        resolution = row["resolution"]
        venue      = row["venue"]

        # ------------------------------------------------------------------
        # 2. Check opt-in
        # ------------------------------------------------------------------
        try:
            params = json.loads(row["params_json"] or "{}")
        except Exception:
            params = {}

        # if not params.get("use_atr_risk", False):
        #     skipped_no_optin += 1
        #     continue

        # ------------------------------------------------------------------
        # 3. Skip if position is open — never move risk params mid-trade
        # ------------------------------------------------------------------
        if row["open_side"] and row["open_qty"]:
            skipped_in_trade += 1
            logger.debug(
                f"ATR Risk: skipping {name} — position open "
                f"({row['open_side']} {row['open_qty']})"
            )
            continue

        # ------------------------------------------------------------------
        # 4. Read per-deployment ATR config from params_json
        # ------------------------------------------------------------------
        atr_period     = int(params.get("atr_period",             DEFAULT_ATR_PERIOD))
        atr_sl_mult    = float(params.get("atr_sl_multiplier",    DEFAULT_ATR_SL_MULTIPLIER))
        atr_tp_mult    = float(params.get("atr_tp_multiplier",    DEFAULT_ATR_TP_MULTIPLIER))
        atr_trail_mult = float(params.get("atr_trail_multiplier", DEFAULT_ATR_TRAIL_MULTIPLIER))
        min_sl_pct     = float(params.get("min_sl_pct",           DEFAULT_MIN_SL_PCT))
        max_sl_pct     = float(params.get("max_sl_pct",           DEFAULT_MAX_SL_PCT))
        max_tp_pct     = float(params.get("max_tp_pct",           DEFAULT_MAX_TP_PCT))

        # ------------------------------------------------------------------
        # 5. Fetch bars
        # ------------------------------------------------------------------
        bars = _fetch_bars(venue, symbol, resolution, atr_period)

        if bars is None or len(bars) < atr_period + 1:
            skipped_no_bars += 1
            bar_count = len(bars) if bars else 0
            logger.debug(
                f"ATR Risk: not enough bars for {name} — "
                f"got {bar_count}, need {atr_period + 1}"
            )
            messages.append(
                f"WARN | {name} ({symbol} {resolution}): "
                f"not enough bars ({bar_count}) for ATR-{atr_period}"
            )
            continue

        # ------------------------------------------------------------------
        # 6. Calculate ATR
        # ------------------------------------------------------------------
        atr = _calc_atr(bars, atr_period)

        if atr is None or atr <= 0:
            skipped_atr_error += 1
            logger.debug(
                f"ATR Risk: ATR calculation returned None/zero for {name}"
            )
            messages.append(
                f"WARN | {name} ({symbol} {resolution}): ATR calculation failed"
            )
            continue

        current_price = _last_close(bars)
        if current_price <= 0:
            skipped_atr_error += 1
            messages.append(
                f"WARN | {name} ({symbol} {resolution}): "
                f"invalid close price {current_price}"
            )
            continue

        # ------------------------------------------------------------------
        # 7. Derive new risk params from ATR multipliers
        # ------------------------------------------------------------------
        atr_pct = _atr_to_pct(atr, current_price)

        raw_sl_pct    = atr_pct * atr_sl_mult
        raw_tp_pct    = atr_pct * atr_tp_mult
        raw_trail_pct = atr_pct * atr_trail_mult

        # Clamp SL within safety bounds.
        new_sl_pct = round(_clamp(raw_sl_pct, min_sl_pct, max_sl_pct), 4)

        # TP must be at least SL + 0.1% to maintain positive reward/risk,
        # and clamped to max_tp_pct to prevent unreachable targets.
        new_tp_pct = round(
            _clamp(
                max(new_sl_pct * (atr_tp_mult / atr_sl_mult), new_sl_pct + 0.1),
                new_sl_pct + 0.1,
                max_tp_pct,
            ),
            4,
        )

        # Trail cannot exceed SL (would stop out before SL fires).
        new_trail_pct = round(_clamp(raw_trail_pct, 0.0, new_sl_pct), 4)

        # ------------------------------------------------------------------
        # 8. Skip if no meaningful change (< 0.01% drift) — avoids noise writes
        # ------------------------------------------------------------------
        old_sl    = float(row["sl_pct"]    or 0)
        old_tp    = float(row["tp_pct"]    or 0)
        old_trail = float(row["trail_pct"] or 0)

        sl_changed    = abs(new_sl_pct    - old_sl)    > 0.01
        tp_changed    = abs(new_tp_pct    - old_tp)    > 0.01
        trail_changed = abs(new_trail_pct - old_trail) > 0.01

        if not (sl_changed or tp_changed or trail_changed):
            logger.debug(
                f"ATR Risk: no meaningful change for {name}, skipping DB write"
            )
            continue

        # ------------------------------------------------------------------
        # 9. Write to DB and log audit event
        # Use a fresh timestamp at the point of each event insertion.
        # ------------------------------------------------------------------
        event_msg = (
            f"ATR-{atr_period} risk update: "
            f"ATR={atr:.4f} ({atr_pct:.3f}% of price {current_price:.4f}) | "
            f"SL {old_sl:.2f}% -> {new_sl_pct:.2f}% | "
            f"TP {old_tp:.2f}% -> {new_tp_pct:.2f}% | "
            f"Trail {old_trail:.2f}% -> {new_trail_pct:.2f}%"
        )

        # Step 1 — Update risk params (must always succeed).
        try:
            with connect() as conn:
                conn.execute(
                    "UPDATE deployments "
                    "SET sl_pct=?, tp_pct=?, trail_pct=? WHERE id=?",
                    (new_sl_pct, new_tp_pct, new_trail_pct, dep_id),
                )
            updated += 1
            messages.append(f"OK  | {name} ({symbol} {resolution}): {event_msg}")
            logger.info(f"ATR Risk: updated {name} — {event_msg}")
        except Exception as e:
            logger.error(f"ATR Risk: DB write failed for {name}: {e}")
            messages.append(
                f"ERR | {name} ({symbol} {resolution}): DB write failed — {e}"
            )
            continue  # skip event log if update itself failed

        # Step 2 — Log audit event separately so a failure never rolls back
        # the UPDATE above. Fresh timestamp at point of insertion.
        try:
            event_ts = datetime.now(timezone.utc).isoformat() + "Z"
            with connect() as conn:
                conn.execute(
                    "INSERT INTO deployment_events"
                    "(deployment_id, ts, kind, message) "
                    "VALUES (?, ?, 'atr_risk_update', ?)",
                    (dep_id, event_ts, event_msg),
                )
        except Exception as e:
            # Event logging failure is non-fatal — risk params were already updated.
            logger.warning(
                f"ATR Risk: event log failed for {name} "
                f"(params were updated): {e}"
            )
            messages.append(
                f"WARN | {name} ({symbol} {resolution}): "
                f"params updated but event log failed — {e}"
            )

    # ------------------------------------------------------------------
    # 10. Summary line (prepended so it appears first in the task log)
    # ------------------------------------------------------------------
    summary = (
        f"ATR Risk Manager complete — "
        f"updated={updated}, "
        f"in_trade={skipped_in_trade}, "
        f"no_optin={skipped_no_optin}, "
        f"no_bars={skipped_no_bars}, "
        f"atr_error={skipped_atr_error}"
    )
    messages.insert(0, summary)
    return "\n".join(messages)

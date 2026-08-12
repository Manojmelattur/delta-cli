"""
multi_tp_deployer.py — Helper to deploy bots with multi-level take-profit.

Usage examples:

    # Deploy BTCUSD with 3 TP levels (partial closes at 1%, 3%, full at 5%)
    python multi_tp_deployer.py --symbol BTCUSD --strategy smc_ob --timeframe 15m \
        --sl-pct 1.5 --tp-levels '[{"pct":1.0,"qty_pct":30},{"pct":3.0,"qty_pct":50},{"pct":5.0,"qty_pct":100}]'
        --venue paper --leverage 10

    # Deploy with ATR-based TP levels
    python multi_tp_deployer.py --symbol ETHUSD --strategy ema_cross --timeframe 1h \
        --sl-pct 2.0 --tp-levels '[{"type":"atr","pct":1.0,"qty_pct":50},{"type":"atr","pct":2.5,"qty_pct":100}]' \
        --venue paper --leverage 5

The framework's scheduler already handles multi-TP natively via params_json:
    params_json = '{"tp_levels": [...], "tp_hits": []}'

Each level supports:
    pct       : profit target percentage (default type)
    type      : "pct" | "point" | "atr"
    qty_pct   : percentage of position to close at this level (1-100, default 100)
    atr_value : required if type="atr" (or set "atr" in params_json separately)
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add delta-cli to path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from delta_bt.store.db import connect


DEFAULT_TP_LEVELS = [
    {"pct": 1.0, "qty_pct": 30},   # TP1: 1% profit, close 30%
    {"pct": 3.0, "qty_pct": 50},   # TP2: 3% profit, close 50% (total 80%)
    {"pct": 5.0, "qty_pct": 100},   # TP3: 5% profit, close remaining 100%
]


def deploy_multi_tp(
    symbol: str,
    strategy: str,
    resolution: str,
    venue: str = "paper",
    size: int = 1,
    sl_pct: float = 1.5,
    tp_levels: list = None,
    trail_pct: float = 1.5,
    trail_activate_pct: float = 1.0,
    leverage: float = 10.0,
    i_understand_live: int = 0,
    tag: str = "multi_tp",
    params_extra: dict = None,
) -> int:
    """Deploy a bot with multi-level take-profit.

    The tp_levels list is embedded in params_json. The scheduler's _check_risk_exit()
    reads tp_levels from params_json and calls _close_partial_position() for partial closes.
    """
    if tp_levels is None:
        tp_levels = DEFAULT_TP_LEVELS
    if params_extra is None:
        params_extra = {}

    # Build params_json with multi-TP config
    params = {
        "tp_levels": tp_levels,
        "tp_hits": [],
    }
    params.update(params_extra)

    # For atr-based TP levels, we need atr_value in params
    for level in tp_levels:
        if level.get("type") == "atr" and "atr_value" not in params:
            params["atr_value"] = level.get("atr_value", 50.0)  # fallback

    params_json = json.dumps(params)

    now = datetime.now(timezone.utc).isoformat() + "Z"
    name = f"Multi-TP {strategy} {symbol}"

    with connect() as conn:
        info = conn.execute(
            """INSERT INTO deployments(
                name, venue, strategy, symbol, resolution, size, params_json,
                sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                reduce_only, interval_sec, status, i_understand_live, leverage,
                sync_leverage, force_entry, created_at, started_at, tag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
            (
                name, venue, strategy,
                symbol, resolution, size, params_json,
                sl_pct, 0, trail_pct, trail_activate_pct, 0.5,  # tp_pct=0, let multi-TP handle it
                0, 300,  # reduce_only=0, interval=300s
                i_understand_live, leverage, 1, 0,  # i_understand_live, leverage, sync, force
                now, now, tag,
            ),
        )
        dep_id = info.lastrowid

        conn.execute(
            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
            "VALUES (?, ?, 'multi_tp_deploy', ?)",
            (dep_id, now, f"Deployed with {len(tp_levels)} TP levels: {json.dumps(tp_levels)}"),
        )

    print(f"Deployed bot #{dep_id}: {name}")
    print(f"  Symbol: {symbol}  Strategy: {strategy}  TF: {resolution}")
    print(f"  Venue: {venue}  Size: {size} lot(s)  Leverage: {leverage}x")
    print(f"  SL: {sl_pct}%  Trail: {trail_pct}% (activate at {trail_activate_pct}%)")
    print(f"  TP Levels ({len(tp_levels)}):")
    for i, level in enumerate(tp_levels):
        ltype = level.get("type", "pct")
        pct = level["pct"]
        qty = level.get("qty_pct", 100)
        if ltype == "pct":
            print(f"    TP{i+1}: +{pct}% → close {qty}% of position")
        elif ltype == "point":
            print(f"    TP{i+1}: +{pct} points → close {qty}% of position")
        elif ltype == "atr":
            print(f"    TP{i+1}: +{pct}xATR → close {qty}% of position")

    return int(dep_id) if dep_id else 0


if __name__ == "__main__":
    # Example usage:
    deploy_multi_tp(
        symbol="BTCUSD",
        strategy="smc_ob",
        resolution="15m",
        venue="paper",
        size=1,
        sl_pct=1.5,
        tp_levels=DEFAULT_TP_LEVELS,
        trail_pct=1.5,
        trail_activate_pct=1.0,
        leverage=10.0,
        tag="multi_tp_example",
    )
    print("\nNote: This is a helper script. Use the delta_bt CLI to manage deployments.")

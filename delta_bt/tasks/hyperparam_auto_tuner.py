import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.store.db import connect
from delta_bt.core.engine import run_backtest
from delta_bt.core.types import RunConfig
from delta_bt.core.registry import load_strategy  # Fix 2: correct import
from delta_bt.reports.report import summarize


def run(**kwargs):
    """
    Automated Hyperparameter Auto-Tuner Task.
    Periodically backtests historical data for active deployments, testing parameter
    variations to find high-performing risk and strategy configurations.
    """
    lookback_days = int(kwargs.get("lookback_days", 30))
    auto_apply    = bool(kwargs.get("auto_apply",   False))

    # Fix 1: correct base URL
    client   = DeltaClient(base_url="https://api.india.delta.exchange")
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=lookback_days)

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 6: named column access
        rows = conn.execute(
            "SELECT id, name, strategy, symbol, resolution, "
            "sl_pct, tp_pct, trail_pct, params_json, size "
            "FROM deployments WHERE status='running'"
        ).fetchall()

    if not rows:
        return "Hyperparameter Auto-Tuner: No running deployments to optimize."

    messages = []

    # Parameter search grid
    sl_options    = [1.0, 1.5, 2.0, 2.5]
    tp_options    = [2.0, 3.0, 4.0, 5.0]
    trail_options = [0.0, 0.5, 1.0, 1.5]

    for row in rows:
        dep_id        = row["id"]
        name          = row["name"]
        strategy_name = row["strategy"]
        symbol        = row["symbol"]
        res           = row["resolution"]

        try:
            current_params = json.loads(row["params_json"] or "{}")
        except Exception:
            current_params = {}

        # Fix 3: use load_history() so run_backtest receives Bar objects not raw dicts
        try:
            bars = load_history(client, symbol, res, start_time, end_time)
        except Exception as e:
            messages.append(f"WARN | {name} ({symbol}): Failed to fetch bars: {e}")
            continue

        if not bars or len(bars) < 50:
            messages.append(
                f"WARN | {name} ({symbol}): Insufficient bars "
                f"({len(bars) if bars else 0}) for tuning."
            )
            continue

        best_score = -999.0
        best_cfg   = None
        best_stats = None

        # Grid search over SL, TP, Trail
        for sl in sl_options:
            for tp in tp_options:
                for trail in trail_options:
                    try:
                        strat_inst = load_strategy(strategy_name, current_params)

                        # Fix 4: include all required RunConfig fields
                        cfg = RunConfig(
                            strategy=strategy_name,
                            symbol=symbol,
                            resolution=res,
                            capital=10000.0,
                            fee_bps=5,
                            slippage_bps=2,
                            sl_pct=sl,
                            tp_pct=tp,
                            trail_pct=trail,
                        )

                        # Fix 5: renamed pf -> result to avoid confusion with profit_factor
                        result = run_backtest(bars, strat_inst, cfg)
                        stats  = summarize(result)

                        pf_val  = float(stats.get("profit_factor", 0) or 0)
                        ret_val = float(stats.get("return_pct",    0) or 0)
                        max_dd  = abs(float(stats.get("max_dd_pct", 0) or 0))

                        score = ret_val * (pf_val if pf_val > 0 else 0.1) / (1.0 + max_dd * 0.1)

                        if score > best_score and ret_val > 0:
                            best_score = score
                            best_cfg   = {"sl_pct": sl, "tp_pct": tp, "trail_pct": trail}
                            best_stats = stats

                    except Exception:
                        continue

        if best_cfg and best_stats:
            new_sl    = best_cfg["sl_pct"]
            new_tp    = best_cfg["tp_pct"]
            new_trail = best_cfg["trail_pct"]
            ret_pct   = float(best_stats.get("return_pct",    0) or 0)
            pf_val    = float(best_stats.get("profit_factor", 0) or 0)

            msg = (
                f"{name} ({symbol} {res}): Best params -> "
                f"SL={new_sl}% TP={new_tp}% Trail={new_trail}% "
                f"(Return={ret_pct:.2f}% PF={pf_val:.2f})"
            )

            if auto_apply:
                now_str = datetime.now(timezone.utc).isoformat() + "Z"

                # Fix 7: split UPDATE and INSERT into separate with blocks
                # so a FK error on the event INSERT never rolls back the UPDATE
                try:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments "
                            "SET sl_pct=?, tp_pct=?, trail_pct=? WHERE id=?",
                            (new_sl, new_tp, new_trail, dep_id),
                        )
                    msg += " [Applied]"
                except Exception as e:
                    messages.append(
                        f"ERR | {name} ({symbol}): DB update failed — {e}"
                    )
                    messages.append(msg)
                    continue

                try:
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'hyper_tuner', ?)",
                            (
                                dep_id, now_str,
                                f"Auto-tuned: SL={new_sl}% TP={new_tp}% "
                                f"Trail={new_trail}% "
                                f"(Return={ret_pct:.2f}% PF={pf_val:.2f})",
                            ),
                        )
                except Exception as e:
                    # Event log failure is non-fatal — params were already updated
                    messages.append(
                        f"WARN | {name} ({symbol}): params updated but event log failed — {e}"
                    )

            messages.append(msg)

        else:
            messages.append(
                f"INFO | {name} ({symbol}): "
                f"Current parameters optimal or no profitable grid found."
            )

    return "\n".join(messages) if messages else "Hyperparameter Auto-Tuner completed."

import json
import sqlite3
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


AUTO_TASKS = (
    "smc_hunter", "vwap_reversion_hunter", "volatility_grid_farmer",
    "volume_anomaly_sniper", "stat_arb_scanner", "scalp_hunter",
)


def run(venue=None, strategy=None, **kwargs):
    # Fix 2: use sqlite3.Row for named column access
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, symbol, strategy, open_side, open_price, "
            "sl_pct, trail_pct, trail_activate_pct, breakeven_after_pct "
            "FROM deployments "
            "WHERE status='running' AND open_side IS NOT NULL"
        ).fetchall()

    if not rows:
        return "No active positions to monitor."

    # Fix 1: use keyword argument for base_url
    client  = DeltaClient(base_url="https://api.india.delta.exchange")
    tickers = {
        t["symbol"]: t
        for t in client.tickers(contract_types="perpetual_futures")
    }

    actions  = 0
    messages = []
    now_str  = datetime.now(timezone.utc).isoformat() + "Z"

    for row in rows:
        sym  = row["symbol"]
        tick = tickers.get(sym)
        if not tick:
            continue

        mark = float(tick.get("mark_price") or tick.get("close") or 0)
        if mark == 0:
            continue

        entry = float(row["open_price"])
        if entry == 0:
            continue

        dep_id = row["id"]
        name   = row["name"]

        if row["open_side"] == "buy":
            drawdown_pct = (entry - mark) / entry * 100
        else:
            drawdown_pct = (mark - entry) / entry * 100

        profit_pct = -drawdown_pct

        # Fix 3: use if/elif/else so only ONE action fires per bot per tick
        if drawdown_pct > 8.0:
            # Tier 2: Emergency FLAT
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET signal_override='FLAT' WHERE id=?",
                        (dep_id,),
                    )
                # Fix 7: log audit event
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'emergency_monitor', ?)",
                        (dep_id, now_str,
                         f"Tier 2 FLAT issued — drawdown {drawdown_pct:.2f}%"),
                    )
                messages.append(
                    f"[Tier 2] Emergency FLAT issued for {name} ({sym}): "
                    f"drawdown={drawdown_pct:.2f}%"
                )
                actions += 1
            except Exception as e:
                messages.append(f"ERR | {name}: Tier 2 action failed — {e}")

        elif drawdown_pct > 4.0:
            # Tier 1: Tighten risk
            current_sl    = float(row["sl_pct"]    or 2.0)
            current_trail = float(row["trail_pct"] or 1.0)

            if current_sl > 0.5 or current_trail > 0.25:
                new_sl    = max(current_sl    * 0.5, 0.25)
                new_trail = max(current_trail * 0.5, 0.10)
                try:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments SET sl_pct=?, trail_pct=? WHERE id=?",
                            (new_sl, new_trail, dep_id),
                        )
                    # Fix 7: log audit event
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'emergency_monitor', ?)",
                            (dep_id, now_str,
                             f"Tier 1 risk tightened — drawdown {drawdown_pct:.2f}% "
                             f"SL {current_sl:.2f}%->{new_sl:.2f}% "
                             f"Trail {current_trail:.2f}%->{new_trail:.2f}%"),
                        )
                    messages.append(
                        f"[Tier 1] Risk tightened for {name} ({sym}): "
                        f"drawdown={drawdown_pct:.2f}% "
                        f"SL={new_sl:.2f}% Trail={new_trail:.2f}%"
                    )
                    actions += 1
                except Exception as e:
                    messages.append(f"ERR | {name}: Tier 1 action failed — {e}")

        elif profit_pct > 15.0 and kwargs.get("windfall", True):
            # Windfall: capture massive profit
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET signal_override='FLAT' WHERE id=?",
                        (dep_id,),
                    )
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'emergency_monitor', ?)",
                        (dep_id, now_str,
                         f"Windfall FLAT — profit {profit_pct:.2f}%"),
                    )
                messages.append(
                    f"[Windfall] Profit captured for {name} ({sym}): "
                    f"profit={profit_pct:.2f}%"
                )
                actions += 1
            except Exception as e:
                messages.append(f"ERR | {name}: Windfall action failed — {e}")

        elif profit_pct > 6.0 and kwargs.get("ratchet", True):
            # Ratchet: tighten trail to lock in profit
            current_trail = float(row["trail_pct"] or 1.0)
            if current_trail > 0.3:
                try:
                    with connect() as conn:
                        conn.execute(
                            # Fix 8: keep trail_activate_pct at current value
                            # setting it to 0 would immediately stop out a profitable position
                            "UPDATE deployments SET trail_pct=0.25 WHERE id=?",
                            (dep_id,),
                        )
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'emergency_monitor', ?)",
                            (dep_id, now_str,
                             f"Ratchet trail tightened — profit {profit_pct:.2f}% "
                             f"trail {current_trail:.2f}%->0.25%"),
                        )
                    messages.append(
                        f"[Ratchet] Trail tightened for {name} ({sym}): "
                        f"profit={profit_pct:.2f}% TSL=0.25%"
                    )
                    actions += 1
                except Exception as e:
                    messages.append(f"ERR | {name}: Ratchet action failed — {e}")

        elif profit_pct > 2.0 and kwargs.get("breakeven", True):
            # Breakeven: use breakeven_after_pct mechanism not sl_pct=0
            current_sl = float(row["sl_pct"] or 2.0)
            if current_sl > 0.05:
                try:
                    with connect() as conn:
                        # Fix 4: use breakeven_after_pct instead of sl_pct=0
                        # sl_pct=0 disables the stop loss entirely in the scheduler
                        conn.execute(
                            "UPDATE deployments SET breakeven_after_pct=? WHERE id=?",
                            (round(profit_pct * 0.5, 2), dep_id),
                        )
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'emergency_monitor', ?)",
                            (dep_id, now_str,
                             f"Breakeven lock engaged — profit {profit_pct:.2f}%"),
                        )
                    messages.append(
                        f"[Breakeven] Lock engaged for {name} ({sym}): "
                        f"profit={profit_pct:.2f}% — breakeven_after_pct set"
                    )
                    actions += 1
                except Exception as e:
                    messages.append(f"ERR | {name}: Breakeven action failed — {e}")

    # Fix 5: check message content only, not actions counter
    tier2_triggered = any("Tier 2" in msg for msg in messages)
    tier1_triggered = any("Tier 1" in msg for msg in messages)

    placeholders = ",".join(["?"] * len(AUTO_TASKS))

    if tier2_triggered:
        try:
            with connect() as conn:
                conn.execute(
                    f"UPDATE background_tasks SET status='paused' "
                    f"WHERE script_name IN ({placeholders})",
                    AUTO_TASKS,
                )
            messages.append(
                "[System] Tier 2 Emergency: All auto-deploy tasks paused."
            )
            actions += 1
        except Exception as e:
            messages.append(f"ERR | System: failed to pause auto tasks — {e}")

    elif tier1_triggered:
        # Fix 6: json already imported at top of file
        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                tasks = conn.execute(
                    f"SELECT id, params_json, script_name FROM background_tasks "
                    f"WHERE script_name IN ({placeholders})",
                    AUTO_TASKS,
                ).fetchall()

            slashed = 0
            for t in tasks:
                try:
                    params      = json.loads(t["params_json"] or "{}")
                    current_lot = float(params.get("base_lot_size", 1.0))
                    if current_lot > 0.1:
                        params["base_lot_size"] = round(current_lot * 0.5, 2)
                        with connect() as conn:
                            conn.execute(
                                "UPDATE background_tasks SET params_json=? WHERE id=?",
                                (json.dumps(params), t["id"]),
                            )
                        slashed += 1
                except Exception as e:
                    messages.append(
                        f"ERR | task {t['script_name']}: lot slash failed — {e}"
                    )

            if slashed > 0:
                messages.append(
                    f"[System] Tier 1 Emergency: base_lot_size slashed 50% "
                    f"across {slashed} auto-deploy tasks."
                )
                actions += 1
        except Exception as e:
            messages.append(f"ERR | System: failed to slash lot sizes — {e}")

    if actions > 0:
        return "### Emergency Monitor Actioned\n\n" + "\n\n".join(messages)
    return f"Monitored {len(rows)} active positions safely. No emergencies detected."

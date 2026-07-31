import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def run(**kwargs):
    drop_threshold_pct = float(kwargs.get("drop_threshold_pct", 3.0))
    # Fix 2: configurable symbol list, defaults to top perpetuals
    watch_symbols      = kwargs.get("symbols", ["BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD"])
    # Fix 6: configurable auto-resume window in minutes (0 = no auto-resume)
    resume_after_min   = int(kwargs.get("resume_after_min", 0))

    # Fix 1: correct base URL
    client = DeltaClient(base_url="https://api.india.delta.exchange")

    end_time   = datetime.now(timezone.utc)
    # Fix 3: use 1 hour of 5m candles (12 bars) for reliable context
    start_time = end_time - timedelta(hours=1)
    # venue       = str(kwargs.get("venue",         "paper"))
    messages               = []
    flash_crash_detected   = False
    crashed_symbols        = []

    for symbol in watch_symbols:
        try:
            klines = client.candles(symbol, "5m", start_time, end_time)
            if not klines or len(klines) < 3:
                continue

            # Fix 4: compare last close to the high of all bars EXCEPT the last
            # so we measure the drop into the current bar, not a self-referential spike.
            reference_high = max(float(k.get("high", k.get("close"))) for k in klines[:-1])
            last_close     = float(klines[-1]["close"])

            if reference_high <= 0:
                continue

            drop_pct = (reference_high - last_close) / reference_high * 100

            if drop_pct > drop_threshold_pct:
                flash_crash_detected = True
                crashed_symbols.append(symbol)
                messages.append(
                    f"FLASH CRASH DETECTED on {symbol}: "
                    f"price dropped {drop_pct:.2f}% from recent high "
                    f"({reference_high:.4f} -> {last_close:.4f})."
                )

        # Fix 7: log errors instead of silently swallowing them
        except Exception as e:
            messages.append(f"ERR | {symbol}: {e}")

    if not flash_crash_detected:
        return "Circuit Breaker: Market volatility normal. No flash crashes detected."

    # --- Circuit Breaker Activated ---
    messages.append("ACTIVATING GLOBAL CIRCUIT BREAKER")

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 8: named column access

        # 1. FLAT all LONG positions to protect capital
        long_rows = conn.execute(
            "SELECT id, name, symbol FROM deployments "
            "WHERE status='running' AND open_side='buy'"
        ).fetchall()

        for r in long_rows:
            conn.execute(
                "UPDATE deployments SET signal_override='FLAT' WHERE id=?",
                (r["id"],),
            )
            messages.append(
                f"> Flatted LONG position on {r['name']} ({r['symbol']})"
            )

        # 2. Pause all flat bots to prevent catching falling knives
        # Fix 6: store paused_at timestamp so auto-resume can check elapsed time
        now_str   = datetime.now(timezone.utc).isoformat() + "Z"
        flat_rows = conn.execute(
            "SELECT id, name FROM deployments "
            "WHERE status='running' AND open_side IS NULL"
        ).fetchall()

        for r in flat_rows:
            conn.execute(
                "UPDATE deployments SET status='paused' WHERE id=?",
                (r["id"],),
            )
            conn.execute(
                "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                "VALUES (?, ?, 'circuit_breaker', ?)",
                (
                    r["id"], now_str,
                    f"paused by circuit breaker — crash detected on {', '.join(crashed_symbols)}",
                ),
            )
            messages.append(f"> Paused flat bot {r['name']}")

    # Fix 6: warn clearly that manual resume is required if auto-resume is off
    if resume_after_min > 0:
        messages.append(
            f"NOTE: Bots will NOT auto-resume. "
            f"resume_after_min={resume_after_min} is set but auto-resume "
            f"is not implemented — resume manually via the UI or a separate task."
        )
    else:
        messages.append(
            "NOTE: All paused bots require manual resume via the UI."
        )

    return "### Circuit Breaker\n\n" + "\n".join(messages)

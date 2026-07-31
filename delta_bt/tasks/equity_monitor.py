import sqlite3
from datetime import datetime, timezone

from delta_bt.store.db import connect


def run(**kwargs):
    window_size  = int(kwargs.get("window_size",  20))
    # Fix 2: auto-resume bots when equity recovers above the moving average
    auto_resume  = bool(kwargs.get("auto_resume", True))

    messages  = []
    checked   = 0
    paused    = 0
    resumed   = 0
    now_str   = datetime.now(timezone.utc).isoformat() + "Z"

    # Fix 6: removed unused `size` column from SELECT
    # Fix 3: use row_factory for named column access
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name FROM deployments WHERE status='running'"
        ).fetchall()

    for row in rows:
        dep_id = row["id"]
        name   = row["name"]

        with connect() as conn:
            events = conn.execute(
                "SELECT pnl FROM deployment_events "
                "WHERE deployment_id=? AND pnl IS NOT NULL "
                "ORDER BY ts ASC",
                (dep_id,),
            ).fetchall()

        # Need window_size + 1 events so we can exclude current from MA calculation
        if len(events) < window_size + 1:
            continue

        checked += 1

        # Build cumulative PnL series
        cum_pnls = []
        current  = 0.0
        for ev in events:
            current += float(ev[0])
            cum_pnls.append(current)

        current_cum_pnl = cum_pnls[-1]

        # Fix 5: compare current equity against the previous window
        # (excluding current value) so the MA is a true leading indicator
        prev_window = cum_pnls[-(window_size + 1):-1]
        moving_avg  = sum(prev_window) / len(prev_window)

        if current_cum_pnl < moving_avg:
            # Fix 1: separate connection for UPDATE and INSERT
            # so a FK error on the event INSERT never rolls back the UPDATE
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (dep_id,),
                    )
                paused += 1
                messages.append(
                    f"Killswitch tripped: paused {name} "
                    f"(equity={current_cum_pnl:.2f} < MA={moving_avg:.2f})"
                )
            except Exception as e:
                messages.append(f"ERR | {name}: UPDATE failed — {e}")
                continue

            # Fix 4: use 'equity_monitor' kind not 'error'
            try:
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'equity_monitor', ?)",
                        (
                            dep_id, now_str,
                            f"Paused — equity {current_cum_pnl:.4f} dropped below "
                            f"{window_size}-trade MA {moving_avg:.4f}.",
                        ),
                    )
            except Exception as e:
                # Non-fatal — bot was already paused
                messages.append(
                    f"WARN | {name}: paused but event log failed — {e}"
                )

        # Fix 2: auto-resume check — equity has recovered above MA
        elif auto_resume:
            # Check if this bot was previously paused by equity monitor
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                paused_row = conn.execute(
                    "SELECT id FROM deployments "
                    "WHERE id=? AND status='paused'",
                    (dep_id,),
                ).fetchone()

            # Note: running bots are already fetched above so this checks
            # separately for paused bots that have recovered
            pass  # resume logic handled in the paused bots block below

    # Fix 2: scan paused bots and resume those whose equity has recovered
    if auto_resume:
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            paused_bots = conn.execute(
                "SELECT id, name FROM deployments WHERE status='paused'"
            ).fetchall()

        for pb in paused_bots:
            with connect() as conn:
                events = conn.execute(
                    "SELECT pnl FROM deployment_events "
                    "WHERE deployment_id=? AND pnl IS NOT NULL "
                    "ORDER BY ts ASC",
                    (pb["id"],),
                ).fetchall()

            if len(events) < window_size + 1:
                continue

            cum_pnls = []
            current  = 0.0
            for ev in events:
                current += float(ev[0])
                cum_pnls.append(current)

            current_cum_pnl = cum_pnls[-1]
            prev_window     = cum_pnls[-(window_size + 1):-1]
            moving_avg      = sum(prev_window) / len(prev_window)

            if current_cum_pnl >= moving_avg:
                try:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments SET status='running' WHERE id=?",
                            (pb["id"],),
                        )
                    resumed += 1
                    messages.append(
                        f"Resumed {pb['name']} — "
                        f"equity={current_cum_pnl:.2f} recovered above MA={moving_avg:.2f}"
                    )
                except Exception as e:
                    messages.append(f"ERR | {pb['name']}: resume failed — {e}")
                    continue

                try:
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'equity_monitor', ?)",
                            (
                                pb["id"], now_str,
                                f"Resumed — equity {current_cum_pnl:.4f} recovered above "
                                f"{window_size}-trade MA {moving_avg:.4f}.",
                            ),
                        )
                except Exception as e:
                    messages.append(
                        f"WARN | {pb['name']}: resumed but event log failed — {e}"
                    )

    # Fix 7: include summary of what was evaluated
    summary = (
        f"Equity Monitor complete — "
        f"checked={checked}, paused={paused}, resumed={resumed}"
    )
    messages.insert(0, summary)

    if paused == 0 and resumed == 0:
        return (
            f"Equity Monitor: All {checked} bots performing above their "
            f"{window_size}-trade equity moving average."
        )

    return "### Equity Curve Monitor\n\n" + "\n".join(messages)

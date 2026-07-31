"""Position Age Monitor Task

Closes positions that have been open longer than max_position_age_hours
without hitting SL/TP. Prevents zombie trades that are stuck open
indefinitely consuming margin and distorting PnL reporting.

Params (set in task params_json):
    max_position_age_hours : Max hours a position can stay open (default 48)
    warn_at_hours          : Log a warning event at this age before closing (default 24)
    auto_close             : If True, issues FLAT signal to close (default False)
    venue_filter           : Only act on this venue e.g. "live", "paper" (default all)
"""
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.store.db import connect


def _position_age_hours(open_price_ts: str) -> float:
    """Calculate how many hours a position has been open.

    Uses the deployment's last entry event timestamp.
    Returns 0.0 if timestamp cannot be parsed.
    """
    if not open_price_ts:
        return 0.0
    try:
        opened = datetime.fromisoformat(
            open_price_ts.replace("Z", "+00:00")
        )
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0
    except Exception:
        return 0.0


def run(**kwargs):
    max_age_hours  = float(kwargs.get("max_position_age_hours", 48.0))
    warn_at_hours  = float(kwargs.get("warn_at_hours",          24.0))
    auto_close     = bool(kwargs.get("auto_close",              False))
    venue_filter   = kwargs.get("venue_filter",                 None)

    now_str = datetime.now(timezone.utc).isoformat() + "Z"

    # Cutoff timestamp for max age
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    ).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Fetch all running deployments with an open position
        # We join to the last entry event to get the entry timestamp
        query = """
            SELECT
                d.id,
                d.name,
                d.symbol,
                d.venue,
                d.open_side,
                d.open_price,
                d.open_qty,
                d.sl_pct,
                d.tp_pct,
                e.ts AS entry_ts
            FROM deployments d
            LEFT JOIN deployment_events e
                ON e.deployment_id = d.id
                AND e.kind = 'entry'
                AND e.id = (
                    SELECT MAX(e2.id)
                    FROM deployment_events e2
                    WHERE e2.deployment_id = d.id
                      AND e2.kind = 'entry'
                )
            WHERE d.status = 'running'
              AND d.open_side IS NOT NULL
              AND d.open_qty  IS NOT NULL
        """
        args = []
        if venue_filter:
            query += " AND d.venue = ?"
            args.append(venue_filter)

        rows = conn.execute(query, args).fetchall()

    if not rows:
        return "Position Age Monitor: No open positions to monitor."

    messages    = []
    checked     = 0
    warned      = 0
    closed      = 0
    errors      = []

    for row in rows:
        checked += 1
        dep_id    = row["id"]
        name      = row["name"]
        symbol    = row["symbol"]
        venue     = row["venue"]
        open_side = row["open_side"]
        open_qty  = float(row["open_qty"]   or 0)
        entry_ts  = row["entry_ts"]

        age_hours = _position_age_hours(entry_ts)

        if age_hours < warn_at_hours:
            # Position is young — no action needed
            continue

        if age_hours >= max_age_hours:
            # Position has exceeded max age
            messages.append(
                f"STALE POSITION: {name} ({symbol} {open_side} {open_qty}) "
                f"open for {age_hours:.1f}h (max={max_age_hours:.0f}h)"
            )

            if auto_close:
                try:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments SET signal_override='FLAT' WHERE id=?",
                            (dep_id,),
                        )
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'position_age_monitor', ?)",
                            (
                                dep_id, now_str,
                                f"FLAT signal issued — position age "
                                f"{age_hours:.1f}h exceeded limit "
                                f"{max_age_hours:.0f}h",
                            ),
                        )
                    messages.append(
                        f"> FLAT signal issued for {name} "
                        f"({age_hours:.1f}h open)."
                    )
                    closed += 1
                except Exception as e:
                    err = f"ERR | {name}: close failed — {e}"
                    errors.append(err)
                    messages.append(err)
            else:
                messages.append(
                    f"> auto_close=False — no action taken. "
                    f"Set auto_close=true in params_json to enable."
                )

        elif age_hours >= warn_at_hours:
            # Position is approaching max age — warn only
            remaining = max_age_hours - age_hours
            messages.append(
                f"AGE WARNING: {name} ({symbol} {open_side}) "
                f"open for {age_hours:.1f}h — "
                f"{remaining:.1f}h until auto-close."
            )
            try:
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'position_age_monitor', ?)",
                        (
                            dep_id, now_str,
                            f"Age warning — position open {age_hours:.1f}h, "
                            f"limit={max_age_hours:.0f}h, "
                            f"{remaining:.1f}h remaining",
                        ),
                    )
                warned += 1
            except Exception as e:
                errors.append(f"ERR | {name}: event log failed — {e}")

    if not messages:
        return (
            f"Position Age Monitor: All {checked} open positions "
            f"are within the {max_age_hours:.0f}h age limit."
        )

    summary = (
        f"Position Age Monitor complete — "
        f"checked={checked}, "
        f"warned={warned}, "
        f"closed={closed}"
    )
    messages.insert(0, summary)

    if errors:
        messages.append("Errors:")
        messages.extend(errors)

    return "### Position Age Monitor\n\n" + "\n".join(messages)

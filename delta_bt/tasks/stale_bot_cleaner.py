"""Stale Bot Cleaner Task

Detects and pauses bots that have stopped ticking — i.e. their
last_tick_at is older than max_stale_hours. This catches bots
that are stuck in an error state, have lost connectivity, or
were never properly started.

A bot is considered stale if:
  - status = 'running'
  - last_tick_at is older than max_stale_hours
  - OR last_tick_at is NULL and created_at is older than grace_period_hours

Stale bots are paused and a deployment_events record is written
so the cause can be investigated via the UI.

Params (set in task params_json):
    max_stale_hours      : Hours without a tick before bot is stale (default 2)
    grace_period_hours   : Hours to wait before flagging a never-ticked bot (default 1)
    auto_pause           : If True, pauses stale bots (default False)
    venue_filter         : Only check this venue (default all)
"""
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.store.db import connect


def _hours_since(ts_str: str) -> float:
    """Return hours elapsed since a timestamp string. Returns 999 if unparseable."""
    if not ts_str:
        return 999.0
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return 999.0


def run(**kwargs):
    max_stale_hours    = float(kwargs.get("max_stale_hours",    2.0))
    grace_period_hours = float(kwargs.get("grace_period_hours", 1.0))
    auto_pause         = bool(kwargs.get("auto_pause",          False))
    venue_filter       = kwargs.get("venue_filter",             None)

    now_str = datetime.now(timezone.utc).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        query = """
            SELECT
                id, name, symbol, strategy, venue,
                resolution, last_tick_at, created_at,
                last_error
            FROM deployments
            WHERE status = 'running'
        """
        args = []
        if venue_filter:
            query += " AND venue = ?"
            args.append(venue_filter)

        rows = conn.execute(query, args).fetchall()

    if not rows:
        return "Stale Bot Cleaner: No running deployments to check."

    messages  = []
    checked   = 0
    healthy   = 0
    stale     = 0
    paused    = 0
    errors    = []

    for row in rows:
        checked += 1
        dep_id     = row["id"]
        name       = row["name"]
        symbol     = row["symbol"]
        venue      = row["venue"]
        last_tick  = row["last_tick_at"]
        created_at = row["created_at"]
        last_error = row["last_error"]

        # Determine staleness
        if last_tick:
            hours_since_tick = _hours_since(last_tick)
            is_stale         = hours_since_tick >= max_stale_hours
            stale_reason     = (
                f"no tick for {hours_since_tick:.1f}h "
                f"(max={max_stale_hours:.1f}h)"
            )
        else:
            # Never ticked — check against grace period
            hours_since_created = _hours_since(created_at)
            is_stale            = hours_since_created >= grace_period_hours
            stale_reason        = (
                f"never ticked, created {hours_since_created:.1f}h ago "
                f"(grace={grace_period_hours:.1f}h)"
            )

        if not is_stale:
            healthy += 1
            continue

        stale += 1
        error_hint = f" last_error={last_error[:80]}" if last_error else ""
        messages.append(
            f"STALE | {name} ({symbol} {venue}): {stale_reason}{error_hint}"
        )

        # Log warning event
        try:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO deployment_events"
                    "(deployment_id, ts, kind, message) "
                    "VALUES (?, ?, 'stale_bot_cleaner', ?)",
                    (
                        dep_id, now_str,
                        f"Stale bot detected — {stale_reason}"
                        + (f" | last_error: {last_error}" if last_error else ""),
                    ),
                )
        except Exception as e:
            errors.append(f"ERR | {name}: event log failed — {e}")

        if auto_pause:
            try:
                with connect() as conn:
                    conn.execute(
                        "UPDATE deployments SET status='paused' WHERE id=?",
                        (dep_id,),
                    )
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'stale_bot_cleaner', ?)",
                        (
                            dep_id, now_str,
                            f"Bot paused by stale cleaner — {stale_reason}",
                        ),
                    )
                paused += 1
                messages.append(
                    f"  Paused: {name} — {stale_reason}"
                )
            except Exception as e:
                err = f"ERR | {name}: pause failed — {e}"
                errors.append(err)
                messages.append(f"  {err}")
        else:
            messages.append(
                f"  auto_pause=False — no action taken."
            )

    summary = (
        f"Stale Bot Cleaner complete — "
        f"checked={checked}, "
        f"healthy={healthy}, "
        f"stale={stale}, "
        f"paused={paused}"
    )

    if not messages:
        return (
            f"### Stale Bot Cleaner\n\n"
            f"{summary}\n"
            f"All {checked} running bots are ticking normally."
        )

    messages.insert(0, summary)

    if not auto_pause and stale > 0:
        messages.append(
            "Note: Set auto_pause=true in params_json to automatically "
            "pause stale bots."
        )

    if errors:
        messages.append("Errors:")
        messages.extend(errors)

    return "### Stale Bot Cleaner\n\n" + "\n".join(messages)

"""News Blackout Task

Pauses all auto-deploy tasks and flat bots during configured
high-impact economic event windows to prevent entering trades
during extreme volatility caused by news events.

Common high-impact events:
  FOMC    : Federal Reserve interest rate decisions
  CPI     : Consumer Price Index inflation data
  NFP     : Non-Farm Payrolls employment data
  GDP     : Gross Domestic Product releases
  OPEC    : Oil production decisions (affects crypto indirectly)
  BTC ETF : Bitcoin ETF approval/rejection news

How it works:
  1. Reads blackout_windows from params_json (list of event dicts)
  2. Checks if current UTC time falls within any blackout window
  3. If inside a window:
       - Pauses all flat running bots
       - Pauses all auto-deploy background tasks
       - Logs blackout event to deployment_events
  4. If outside all windows:
       - Resumes bots and tasks paused by this task
       - Logs resume event

Blackout window format (in params_json):
  {
    "blackout_windows": [
      {
        "name":       "FOMC Decision",
        "date":       "2026-07-30",
        "start_utc":  "18:00",
        "end_utc":    "20:00",
        "recurrence": "once"
      },
      {
        "name":       "Monthly CPI",
        "weekday":    null,
        "start_utc":  "12:30",
        "end_utc":    "13:30",
        "recurrence": "monthly",
        "day_of_month": 10
      },
      {
        "name":       "Weekly NFP",
        "start_utc":  "12:30",
        "end_utc":    "13:30",
        "recurrence": "weekly",
        "weekday":    4
      }
    ]
  }

Recurrence types:
  once     : specific date (requires "date" field YYYY-MM-DD)
  daily    : every day at the specified time
  weekly   : every week on weekday (0=Mon, 4=Fri, 6=Sun)
  monthly  : every month on day_of_month

Params (set in task params_json):
    blackout_windows     : List of event window dicts (see above)
    pause_bots           : If True, pauses flat bots during blackout (default True)
    pause_tasks          : If True, pauses auto-deploy tasks during blackout (default True)
    venue_filter         : Only manage bots on this venue (default all)
    buffer_minutes       : Extra minutes to add before/after each window (default 5)
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from delta_bt.store.db import connect


_BLACKOUT_TAG  = "news_blackout"
_BLACKOUT_KEY  = "market.news_blackout"

_AUTO_DEPLOY_TASKS = (
    "smc_hunter", "keltner_hunter", "vwap_reversion_hunter",
    "volatility_grid_farmer", "volume_anomaly_sniper",
    "stat_arb_scanner", "scalp_hunter", "runner_fleet_hunter",
    "strategy_hunter", "liquidation_cascade_hunter",
    "anti_correlation_deployer", "session_aware_deployer",
)


def _parse_time(time_str: str) -> tuple:
    """Parse HH:MM string into (hour, minute) tuple."""
    try:
        parts = time_str.strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def _is_in_window(
    now: datetime,
    window: dict,
    buffer_minutes: int,
) -> tuple:
    """Check if current time falls within a blackout window.

    Returns (is_active, window_name, start_dt, end_dt).
    """
    name        = window.get("name", "Unknown Event")
    recurrence  = window.get("recurrence", "once")
    start_str   = window.get("start_utc", "00:00")
    end_str     = window.get("end_utc",   "01:00")

    start_h, start_m = _parse_time(start_str)
    end_h,   end_m   = _parse_time(end_str)

    today = now.date()

    # Determine candidate date(s) to check
    candidate_dates = []

    if recurrence == "once":
        date_str = window.get("date", "")
        try:
            from datetime import date
            candidate_dates.append(
                datetime.strptime(date_str, "%Y-%m-%d").date()
            )
        except Exception:
            return False, name, None, None

    elif recurrence == "daily":
        candidate_dates.append(today)

    elif recurrence == "weekly":
        weekday = int(window.get("weekday", 4))  # default Friday
        # Check today and yesterday (in case window spans midnight)
        for delta in [0, -1]:
            d = today + timedelta(days=delta)
            if d.weekday() == weekday:
                candidate_dates.append(d)

    elif recurrence == "monthly":
        day_of_month = int(window.get("day_of_month", 1))
        # Check this month and last month
        for delta_months in [0, -1]:
            try:
                month = today.month + delta_months
                year  = today.year
                if month <= 0:
                    month += 12
                    year  -= 1
                from datetime import date
                candidate_dates.append(date(year, month, day_of_month))
            except Exception:
                pass

    # Check if now falls within any candidate window
    buf = timedelta(minutes=buffer_minutes)

    for candidate_date in candidate_dates:
        start_dt = datetime(
            candidate_date.year, candidate_date.month, candidate_date.day,
            start_h, start_m, tzinfo=timezone.utc,
        ) - buf

        # Handle windows that cross midnight
        end_dt = datetime(
            candidate_date.year, candidate_date.month, candidate_date.day,
            end_h, end_m, tzinfo=timezone.utc,
        ) + buf

        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        if start_dt <= now <= end_dt:
            return True, name, start_dt, end_dt

    return False, name, None, None


def run(**kwargs):
    blackout_windows = kwargs.get("blackout_windows", [])
    pause_bots       = bool(kwargs.get("pause_bots",   True))
    pause_tasks      = bool(kwargs.get("pause_tasks",  True))
    venue_filter     = kwargs.get("venue_filter",      None)
    buffer_minutes   = int(kwargs.get("buffer_minutes", 5))

    now     = datetime.now(timezone.utc)
    now_str = now.isoformat() + "Z"

    messages = [
        "News Blackout Monitor",
        f"  Current time     : {now.strftime('%Y-%m-%d %H:%M')} UTC",
        f"  Blackout windows : {len(blackout_windows)} configured",
        f"  Buffer           : ±{buffer_minutes} minutes",
        f"  Pause bots       : {pause_bots}",
        f"  Pause tasks      : {pause_tasks}",
        "",
    ]

    if not blackout_windows:
        messages.append(
            "No blackout windows configured. "
            "Add blackout_windows to params_json to enable news blackouts. "
            "See task docstring for format."
        )
        return "### News Blackout\n\n" + "\n".join(messages)

    # ------------------------------------------------------------------
    # Check all windows
    # ------------------------------------------------------------------
    active_windows  = []
    upcoming        = []
    errors          = []

    for window in blackout_windows:
        is_active, name, start_dt, end_dt = _is_in_window(
            now, window, buffer_minutes
        )
        if is_active:
            active_windows.append({
                "name":     name,
                "start_dt": start_dt,
                "end_dt":   end_dt,
            })
        else:
            # Check if window is upcoming in next 24h
            # Re-check without buffer for display purposes
            _, _, raw_start, raw_end = _is_in_window(
                now + timedelta(hours=1), window, 0
            )
            if raw_start and raw_start > now:
                hours_until = (raw_start - now).total_seconds() / 3600
                if hours_until <= 24:
                    upcoming.append({
                        "name":        name,
                        "start_dt":    raw_start,
                        "hours_until": hours_until,
                    })

    currently_in_blackout = len(active_windows) > 0

    # ------------------------------------------------------------------
    # Persist blackout state to app_settings
    # ------------------------------------------------------------------
    blackout_payload = json.dumps({
        "active":       currently_in_blackout,
        "active_events":[w["name"] for w in active_windows],
        "updated_at":   now_str,
    })

    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_BLACKOUT_KEY, blackout_payload),
            )
    except Exception as e:
        errors.append(f"ERR | app_settings write failed — {e}")

    paused_bots  = 0
    paused_tasks = 0
    resumed_bots = 0
    resumed_tasks= 0

    # ------------------------------------------------------------------
    # Active blackout — pause bots and tasks
    # ------------------------------------------------------------------
    if currently_in_blackout:
        event_names = ", ".join(w["name"] for w in active_windows)
        end_times   = ", ".join(
            w["end_dt"].strftime("%H:%M UTC")
            for w in active_windows
            if w["end_dt"]
        )

        messages.append(
            f"BLACKOUT ACTIVE: {event_names}"
        )
        for w in active_windows:
            if w["end_dt"]:
                remaining = (w["end_dt"] - now).total_seconds() / 60
                messages.append(
                    f"  {w['name']}: ends {w['end_dt'].strftime('%H:%M UTC')} "
                    f"({remaining:.0f} min remaining)"
                )
        messages.append("")

        # Pause flat running bots
        if pause_bots:
            try:
                with connect() as conn:
                    conn.row_factory = sqlite3.Row

                    query = (
                        "SELECT id, name, venue, strategy, tag "
                        "FROM deployments "
                        "WHERE status='running' AND open_side IS NULL"
                    )
                    args = []
                    if venue_filter:
                        query += " AND venue = ?"
                        args.append(venue_filter)

                    flat_bots = conn.execute(query, args).fetchall()

                for bot in flat_bots:
                    current_tag = bot["tag"] or ""
                    if _BLACKOUT_TAG in current_tag:
                        continue  # already paused by us

                    try:
                        new_tag = (
                            f"{current_tag},{_BLACKOUT_TAG}"
                            if current_tag else _BLACKOUT_TAG
                        )
                        with connect() as conn:
                            conn.execute(
                                "UPDATE deployments "
                                "SET status='paused', tag=? WHERE id=?",
                                (new_tag, bot["id"]),
                            )
                        with connect() as conn:
                            conn.execute(
                                "INSERT INTO deployment_events"
                                "(deployment_id, ts, kind, message) "
                                "VALUES (?, ?, 'news_blackout', ?)",
                                (
                                    bot["id"], now_str,
                                    f"Paused — news blackout active: "
                                    f"{event_names}. "
                                    f"Resumes at {end_times}.",
                                ),
                            )
                        paused_bots += 1
                        messages.append(
                            f"  Paused bot : {bot['name']} "
                            f"({bot['venue']} {bot['strategy']})"
                        )
                    except Exception as e:
                        errors.append(
                            f"ERR | {bot['name']}: pause failed — {e}"
                        )

            except Exception as e:
                errors.append(f"ERR | bot pause query failed — {e}")

            if paused_bots == 0:
                messages.append("  No flat bots to pause.")

        # Pause auto-deploy background tasks
        if pause_tasks:
            try:
                placeholders = ",".join(["?"] * len(_AUTO_DEPLOY_TASKS))
                with connect() as conn:
                    conn.row_factory = sqlite3.Row
                    tasks = conn.execute(
                        f"SELECT id, script_name, status "
                        f"FROM background_tasks "
                        f"WHERE script_name IN ({placeholders}) "
                        f"AND status = 'running'",
                        _AUTO_DEPLOY_TASKS,
                    ).fetchall()

                for task in tasks:
                    try:
                        with connect() as conn:
                            conn.execute(
                                "UPDATE background_tasks "
                                "SET status='paused' WHERE id=?",
                                (task["id"],),
                            )
                        paused_tasks += 1
                        messages.append(
                            f"  Paused task: {task['script_name']}"
                        )
                    except Exception as e:
                        errors.append(
                            f"ERR | task {task['script_name']}: "
                            f"pause failed — {e}"
                        )

            except Exception as e:
                errors.append(f"ERR | task pause query failed — {e}")

            if paused_tasks == 0:
                messages.append("  No auto-deploy tasks to pause.")

    # ------------------------------------------------------------------
    # No active blackout — resume previously paused bots and tasks
    # ------------------------------------------------------------------
    else:
        messages.append(
            f"No active blackout windows. Market is clear."
        )

        # Resume bots paused by this task
        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row

                query = (
                    "SELECT id, name, venue, strategy, tag "
                    "FROM deployments "
                    "WHERE status='paused' "
                    "AND open_side IS NULL "
                    "AND tag LIKE ?"
                )
                args = [f"%{_BLACKOUT_TAG}%"]
                if venue_filter:
                    query += " AND venue = ?"
                    args.append(venue_filter)

                paused_bots_rows = conn.execute(query, args).fetchall()

            for bot in paused_bots_rows:
                try:
                    # Remove blackout tag
                    original_tag = (
                        (bot["tag"] or "")
                        .replace(f",{_BLACKOUT_TAG}", "")
                        .replace(_BLACKOUT_TAG, "")
                        .strip(",")
                    )
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments "
                            "SET status='running', tag=? WHERE id=?",
                            (original_tag or None, bot["id"]),
                        )
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'news_blackout', ?)",
                            (
                                bot["id"], now_str,
                                "Resumed — news blackout window has ended.",
                            ),
                        )
                    resumed_bots += 1
                    messages.append(
                        f"  Resumed bot : {bot['name']} "
                        f"({bot['venue']} {bot['strategy']})"
                    )
                except Exception as e:
                    errors.append(
                        f"ERR | {bot['name']}: resume failed — {e}"
                    )

        except Exception as e:
            errors.append(f"ERR | bot resume query failed — {e}")

        # Resume auto-deploy tasks paused by this task
        try:
            placeholders = ",".join(["?"] * len(_AUTO_DEPLOY_TASKS))
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                paused_task_rows = conn.execute(
                    f"SELECT id, script_name FROM background_tasks "
                    f"WHERE script_name IN ({placeholders}) "
                    f"AND status = 'paused'",
                    _AUTO_DEPLOY_TASKS,
                ).fetchall()

            for task in paused_task_rows:
                try:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE background_tasks "
                            "SET status='running' WHERE id=?",
                            (task["id"],),
                        )
                    resumed_tasks += 1
                    messages.append(
                        f"  Resumed task: {task['script_name']}"
                    )
                except Exception as e:
                    errors.append(
                        f"ERR | task {task['script_name']}: "
                        f"resume failed — {e}"
                    )

        except Exception as e:
            errors.append(f"ERR | task resume query failed — {e}")

        if resumed_bots == 0 and resumed_tasks == 0:
            messages.append(
                "  No bots or tasks were paused by news blackout."
            )

    # ------------------------------------------------------------------
    # Upcoming windows in next 24h
    # ------------------------------------------------------------------
    if upcoming:
        messages.append("")
        messages.append("Upcoming Blackout Windows (next 24h):")
        for u in sorted(upcoming, key=lambda x: x["hours_until"]):
            messages.append(
                f"  {u['name']:<25} in {u['hours_until']:.1f}h "
                f"({u['start_dt'].strftime('%H:%M UTC')})"
            )

    # ------------------------------------------------------------------
    # All configured windows summary
    # ------------------------------------------------------------------
    messages.append("")
    messages.append("All Configured Windows:")
    for w in blackout_windows:
        rec  = w.get("recurrence", "once")
        name = w.get("name", "Unknown")
        start= w.get("start_utc", "?")
        end  = w.get("end_utc",   "?")

        if rec == "once":
            schedule = f"once on {w.get('date', '?')}"
        elif rec == "daily":
            schedule = "daily"
        elif rec == "weekly":
            days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            wd   = int(w.get("weekday", 4))
            schedule = f"every {days[wd] if wd < 7 else '?'}"
        elif rec == "monthly":
            schedule = f"monthly on day {w.get('day_of_month', '?')}"
        else:
            schedule = rec

        messages.append(
            f"  {name:<25} {start}-{end} UTC  [{schedule}]"
            + (" <- ACTIVE" if any(
                aw["name"] == name for aw in active_windows
            ) else "")
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    summary = (
        f"News Blackout complete — "
        f"active={currently_in_blackout}, "
        f"paused_bots={paused_bots}, "
        f"paused_tasks={paused_tasks}, "
        f"resumed_bots={resumed_bots}, "
        f"resumed_tasks={resumed_tasks}"
    )
    messages.insert(
        next(
            (i for i, m in enumerate(messages) if m == ""),
            len(messages),
        ),
        summary,
    )

    if errors:
        messages.append("")
        messages.append("Errors:")
        messages.extend(f"  {e}" for e in errors)

    return "### News Blackout\n\n" + "\n".join(messages)

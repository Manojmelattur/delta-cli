"""Session-Aware Deployer Task

Only allows auto-deployment of new bots during high-liquidity
trading sessions. Prevents bots from entering during low-volume
off-hours where spreads are wide and slippage is high.

Sessions (UTC):
  Asia          : 00:00 - 08:00  (moderate liquidity)
  London        : 08:00 - 13:00  (high liquidity)
  London+NY     : 13:00 - 16:00  (highest liquidity — overlap)
  New York      : 16:00 - 21:00  (high liquidity)
  Off Hours     : 21:00 - 00:00  (low liquidity — avoid)

How it works:
  1. Checks current UTC hour against allowed sessions
  2. If outside allowed sessions — pauses all flat running bots
     to prevent new entries during low-liquidity windows
  3. If inside allowed sessions — resumes previously session-paused bots
  4. Writes current session to app_settings for other tasks to read

Params (set in task params_json):
    allowed_sessions     : List of session names to allow deployment
                           (default ["London", "London+NY", "New York"])
    pause_outside        : If True, pauses flat bots outside sessions (default False)
    resume_inside        : If True, resumes session-paused bots inside sessions (default True)
    venue_filter         : Only manage bots on this venue (default all)
    strategy_filter      : Only manage bots using this strategy (default all)
    tag_filter           : Only manage bots with this tag (default all)
"""
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from delta_bt.store.db import connect


_SESSION_KEY = "market.session"

_SESSIONS = {
    "Asia":      (0,  8),
    "London":    (8,  13),
    "London+NY": (13, 16),
    "New York":  (16, 21),
    "Off Hours": (21, 24),
}

_DEFAULT_ALLOWED = ["London", "London+NY", "New York"]

# Tag used to mark bots paused specifically by this task
# so we only resume bots WE paused, not ones paused by other tasks
_PAUSE_TAG = "session_paused"


def _current_session(hour: int) -> str:
    """Return the trading session name for a given UTC hour."""
    for name, (start, end) in _SESSIONS.items():
        if start <= hour < end:
            return name
    return "Off Hours"


def _session_liquidity(session: str) -> str:
    """Return liquidity description for a session."""
    return {
        "Asia":      "Moderate",
        "London":    "High",
        "London+NY": "Highest (overlap)",
        "New York":  "High",
        "Off Hours": "Low",
    }.get(session, "Unknown")


def run(**kwargs):
    allowed_sessions = kwargs.get(
        "allowed_sessions", _DEFAULT_ALLOWED
    )
    pause_outside    = bool(kwargs.get("pause_outside",  False))
    resume_inside    = bool(kwargs.get("resume_inside",  True))
    venue_filter     = kwargs.get("venue_filter",        None)
    strategy_filter  = kwargs.get("strategy_filter",     None)
    tag_filter       = kwargs.get("tag_filter",          None)

    now        = datetime.now(timezone.utc)
    now_str    = now.isoformat() + "Z"
    hour       = now.hour
    minute     = now.minute

    current_session  = _current_session(hour)
    is_allowed       = current_session in allowed_sessions
    liquidity        = _session_liquidity(current_session)

    # ------------------------------------------------------------------
    # Persist current session to app_settings
    # ------------------------------------------------------------------
    session_payload = json.dumps({
        "session":    current_session,
        "hour_utc":   hour,
        "is_allowed": is_allowed,
        "liquidity":  liquidity,
        "updated_at": now_str,
    })

    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_SESSION_KEY, session_payload),
            )
    except Exception as e:
        pass  # non-fatal — continue with main logic

    messages = [
        f"Session-Aware Deployer",
        f"  Current time     : {now.strftime('%H:%M')} UTC",
        f"  Current session  : {current_session}",
        f"  Liquidity        : {liquidity}",
        f"  Allowed sessions : {', '.join(allowed_sessions)}",
        f"  Status           : {'ALLOWED' if is_allowed else 'BLOCKED'}",
        "",
    ]

    # Show full session schedule
    messages.append("Session Schedule (UTC):")
    for name, (start, end) in _SESSIONS.items():
        active  = " <- CURRENT" if name == current_session else ""
        allowed = " [ALLOWED]"  if name in allowed_sessions else ""
        messages.append(
            f"  {name:<12} {start:02d}:00 - {end:02d}:00  "
            f"{_session_liquidity(name):<20}{allowed}{active}"
        )
    messages.append("")

    paused  = 0
    resumed = 0
    errors  = []

    # ------------------------------------------------------------------
    # Build base query filters
    # ------------------------------------------------------------------
    def _build_filters(extra_where: str = "") -> tuple:
        """Build WHERE clause and args for deployment queries."""
        conditions = [extra_where] if extra_where else []
        args       = []

        if venue_filter:
            conditions.append("venue = ?")
            args.append(venue_filter)
        if strategy_filter:
            conditions.append("strategy = ?")
            args.append(strategy_filter)
        if tag_filter:
            conditions.append("tag = ?")
            args.append(tag_filter)

        where = " AND ".join(conditions) if conditions else "1=1"
        return where, args

    # ------------------------------------------------------------------
    # Outside allowed session — pause flat bots
    # ------------------------------------------------------------------
    if not is_allowed and pause_outside:
        where, args = _build_filters(
            "status='running' AND open_side IS NULL"
        )

        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                flat_bots = conn.execute(
                    f"SELECT id, name, venue, strategy, tag "
                    f"FROM deployments WHERE {where}",
                    args,
                ).fetchall()

            for bot in flat_bots:
                # Skip bots already tagged as session_paused
                # (prevents double-tagging on repeated runs)
                current_tag = bot["tag"] or ""
                if _PAUSE_TAG in current_tag:
                    continue

                try:
                    # Append session_paused to existing tag
                    new_tag = (
                        f"{current_tag},{_PAUSE_TAG}"
                        if current_tag
                        else _PAUSE_TAG
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
                            "VALUES (?, ?, 'session_aware_deployer', ?)",
                            (
                                bot["id"], now_str,
                                f"Paused — outside allowed sessions. "
                                f"Current session: {current_session} "
                                f"({hour:02d}:{minute:02d} UTC). "
                                f"Allowed: {', '.join(allowed_sessions)}",
                            ),
                        )
                    paused += 1
                    messages.append(
                        f"  Paused : {bot['name']} "
                        f"({bot['venue']} {bot['strategy']})"
                    )
                except Exception as e:
                    errors.append(
                        f"ERR | {bot['name']}: pause failed — {e}"
                    )

        except Exception as e:
            errors.append(f"ERR | flat bot query failed — {e}")

        if paused == 0:
            messages.append(
                f"  No flat bots to pause during {current_session}."
            )

    elif not is_allowed and not pause_outside:
        messages.append(
            f"Outside allowed session ({current_session}). "
            f"pause_outside=False — no bots paused. "
            f"Set pause_outside=true in params_json to enable."
        )

    # ------------------------------------------------------------------
    # Inside allowed session — resume session-paused bots
    # ------------------------------------------------------------------
    if is_allowed and resume_inside:
        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                # Only resume bots that were paused by THIS task
                # identified by _PAUSE_TAG in their tag column
                paused_bots = conn.execute(
                    "SELECT id, name, venue, strategy, tag "
                    "FROM deployments "
                    "WHERE status='paused' "
                    "AND open_side IS NULL "
                    "AND tag LIKE ?",
                    (f"%{_PAUSE_TAG}%",),
                ).fetchall()

            for bot in paused_bots:
                # Apply additional filters if set
                if venue_filter and bot["venue"] != venue_filter:
                    continue
                if strategy_filter and bot["strategy"] != strategy_filter:
                    continue

                try:
                    # Remove session_paused from tag
                    original_tag = (
                        (bot["tag"] or "")
                        .replace(f",{_PAUSE_TAG}", "")
                        .replace(_PAUSE_TAG, "")
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
                            "VALUES (?, ?, 'session_aware_deployer', ?)",
                            (
                                bot["id"], now_str,
                                f"Resumed — entered allowed session "
                                f"{current_session} "
                                f"({hour:02d}:{minute:02d} UTC).",
                            ),
                        )
                    resumed += 1
                    messages.append(
                        f"  Resumed: {bot['name']} "
                        f"({bot['venue']} {bot['strategy']})"
                    )
                except Exception as e:
                    errors.append(
                        f"ERR | {bot['name']}: resume failed — {e}"
                    )

        except Exception as e:
            errors.append(f"ERR | paused bot query failed — {e}")

        if resumed == 0 and is_allowed:
            messages.append(
                f"  No session-paused bots to resume during {current_session}."
            )

    # ------------------------------------------------------------------
    # Show next session transition time
    # ------------------------------------------------------------------
    next_session      = None
    next_session_hour = None

    for name, (start, end) in _SESSIONS.items():
        if start > hour:
            next_session      = name
            next_session_hour = start
            break
# Find the next session after current hour
    next_session      = None
    next_session_hour = 0

    if next_session is None:
        # Wrap around to next day
        next_session      = "Asia"
        next_session_hour = 24

    hours_until_next = next_session_hour - hour - (minute / 60)
    next_allowed     = next_session in allowed_sessions

    messages.append(
        f"Next session: {next_session} at {next_session_hour:02d}:00 UTC "
        f"(in {hours_until_next:.1f}h) — "
        f"{'ALLOWED' if next_allowed else 'BLOCKED'}"
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    summary = (
        f"Session-Aware Deployer complete — "
        f"session={current_session}, "
        f"allowed={is_allowed}, "
        f"paused={paused}, "
        f"resumed={resumed}"
    )
    messages.insert(
        next(
            (i for i, m in enumerate(messages) if m == ""),
            len(messages),
        ),
        summary,
    )

    if not pause_outside and not is_allowed:
        messages.append("")
        messages.append(
            "Note: Set pause_outside=true in params_json to automatically "
            "pause flat bots outside allowed sessions."
        )

    if errors:
        messages.append("")
        messages.append("Errors:")
        messages.extend(f"  {e}" for e in errors)

    return "### Session-Aware Deployer\n\n" + "\n".join(messages)

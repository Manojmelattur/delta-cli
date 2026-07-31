import json
import sqlite3
from datetime import datetime, timezone

import requests

from delta_bt.store.db import connect


# Event kinds worth alerting on — excludes noisy tick/evaluation events
# Fix 6: only dispatch meaningful events
_ALERT_KINDS = {
    "entry", "sl_hit", "tp_hit", "sl_slippage", "signal_exit", "flip",
    "error", "bracket_placed", "brackets_healed", "bracket_error",
    "leverage_error", "entry_blocked", "exchange_sync_close",
    "manual_override", "circuit_breaker", "atr_risk_update",
    "delta_hedge", "equity_monitor", "capital_allocator",
    "emergency_monitor", "liquidity_guard", "funding_monitor",
    "kelly_sizing", "mtf_enforcer",
}

_LAST_DISPATCHED_ID_KEY = "webhook_dispatcher.last_id"


def _get_last_dispatched_id(conn) -> int:
    """Fix 1+7: read last dispatched event ID from app_settings for persistence."""
    try:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key=?",
            (_LAST_DISPATCHED_ID_KEY,),
        ).fetchone()
        if row:
            return int(json.loads(row["value_json"]))
    except Exception:
        pass
    return 0


def _set_last_dispatched_id(conn, event_id: int) -> None:
    """Persist last dispatched event ID so restarts do not re-dispatch old events."""
    try:
        conn.execute(
            "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (_LAST_DISPATCHED_ID_KEY, json.dumps(event_id)),
        )
    except Exception:
        pass


def _send_discord(webhook_url: str, text: str) -> tuple[bool, str]:
    """Fix 4+5: use requests, check response status code."""
    try:
        resp = requests.post(
            webhook_url,
            json={"content": text},
            timeout=5,
        )
        if resp.status_code in (200, 204):
            return True, "ok"
        return False, f"HTTP {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        return False, str(e)


def _send_telegram(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Fix 4+5: use requests, check response status code."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            return True, "ok"
        return False, f"HTTP {resp.status_code}: {data.get('description', resp.text[:100])}"
    except Exception as e:
        return False, str(e)


def run(**kwargs):
    """
    Telegram and Discord Alert Hub Task.
    Scans new deployment events since last run and dispatches rich
    real-time notifications to configured Telegram and Discord endpoints.

    Params (set in task params_json):
        telegram_bot_token  : Telegram bot token
        telegram_chat_id    : Telegram chat ID
        discord_webhook_url : Discord webhook URL
        max_events          : Max events to dispatch per run (default 20)
    """
    telegram_bot_token  = kwargs.get("telegram_bot_token",  "")
    telegram_chat_id    = kwargs.get("telegram_chat_id",    "")
    discord_webhook_url = kwargs.get("discord_webhook_url", "")
    max_events          = int(kwargs.get("max_events", 20))

    has_discord  = bool(discord_webhook_url)
    has_telegram = bool(telegram_bot_token and telegram_chat_id)

    if not has_discord and not has_telegram:
        return (
            "Webhook Dispatcher: No endpoints configured. "
            "Set discord_webhook_url or telegram_bot_token + telegram_chat_id "
            "in task params_json."
        )

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 2: named column access

        # Fix 1+7: only fetch events newer than last dispatched ID
        last_id = _get_last_dispatched_id(conn)

        # Fix 6: filter to meaningful event kinds only
        kind_placeholders = ",".join(["?"] * len(_ALERT_KINDS))
        events = conn.execute(
            f"SELECT e.id, d.name, e.ts, e.kind, e.message "
            f"FROM deployment_events e "
            f"JOIN deployments d ON e.deployment_id = d.id "
            f"WHERE e.id > ? AND e.kind IN ({kind_placeholders}) "
            f"ORDER BY e.id ASC LIMIT ?",
            (last_id, *_ALERT_KINDS, max_events),
        ).fetchall()

    if not events:
        return (
            f"Webhook Dispatcher: No new alert-worthy events since last run "
            f"(last_id={last_id})."
        )

    dispatched  = 0
    failed      = 0
    errors      = []
    max_id_seen = last_id

    for ev in events:
        ev_id    = ev["id"]
        bot_name = ev["name"]
        ts       = ev["ts"]
        kind     = ev["kind"]
        msg      = ev["message"] or ""

        # Truncate long messages for notification readability
        msg_short = msg[:200] + "..." if len(msg) > 200 else msg

        text = (
            f"[Delta Bot] {bot_name} | {kind.upper()}\n"
            f"Time: {ts}\n"
            f"{msg_short}"
        )

        ev_dispatched = False

        if has_discord:
            ok, detail = _send_discord(discord_webhook_url, text)
            if ok:
                ev_dispatched = True
            else:
                # Fix 3: log dispatch errors instead of silently passing
                errors.append(f"Discord failed for event {ev_id}: {detail}")
                failed += 1

        if has_telegram:
            ok, detail = _send_telegram(telegram_bot_token, telegram_chat_id, text)
            if ok:
                ev_dispatched = True
            else:
                errors.append(f"Telegram failed for event {ev_id}: {detail}")
                failed += 1

        if ev_dispatched:
            dispatched += 1

        # Track highest ID we attempted regardless of success
        # so we do not retry failed events on next run (avoids spam)
        max_id_seen = max(max_id_seen, ev_id)

    # Fix 1+7: persist last dispatched ID
    if max_id_seen > last_id:
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            _set_last_dispatched_id(conn, max_id_seen)

    lines = [
        f"Webhook Dispatcher: processed {len(events)} new events — "
        f"dispatched={dispatched} failed={failed}"
    ]
    if errors:
        lines.append("Errors:")
        lines.extend(f"  {e}" for e in errors)

    return "\n".join(lines)

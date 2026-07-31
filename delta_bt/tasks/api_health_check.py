"""API Health Check Task

Pings Delta Exchange REST API endpoints and measures response latency.
Alerts if any endpoint is slow, returning errors, or unreachable.

Checks performed:
  1. Public endpoint  — GET /v2/products (no auth required)
  2. Ticker endpoint  — GET /v2/tickers  (no auth required)
  3. Candles endpoint — GET /v2/history/candles (no auth required)
  4. Auth endpoint    — GET /v2/wallet/balances (auth required, live only)
  5. Testnet endpoint — GET /v2/products on testnet base URL

Results are written to app_settings so other tasks can check
API health before placing orders.

Params (set in task params_json):
    warn_latency_ms    : Log warning if response > this ms (default 1000)
    critical_latency_ms: Log critical if response > this ms (default 3000)
    check_auth         : If True, checks authenticated endpoint (default False)
    check_testnet      : If True, checks testnet endpoint (default True)
    alert_on_failure   : If True, pauses all live bots on critical failure (default False)
    test_symbol        : Symbol to use for candles check (default BTCUSD)
"""
import json
import sqlite3
import time
from datetime import datetime, timezone

import requests

from delta_bt.store.db import connect


_BASE_LIVE    = "https://api.india.delta.exchange"
_BASE_TESTNET = "https://cdn-ind.testnet.deltaex.org"
_HEALTH_KEY   = "api.health"


def _ping(
    url: str,
    method: str = "GET",
    headers: dict = None,
    timeout: int = 10,
) -> tuple:
    """Ping a URL and return (status_code, latency_ms, error_str).

    Returns (-1, 0, error_str) on connection failure.
    """
    start = time.monotonic()
    try:
        resp = requests.request(
            method, url,
            headers=headers or {"Accept": "application/json"},
            timeout=timeout,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        return resp.status_code, latency_ms, ""
    except requests.exceptions.Timeout:
        latency_ms = int((time.monotonic() - start) * 1000)
        return -1, latency_ms, "timeout"
    except requests.exceptions.ConnectionError as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return -1, latency_ms, f"connection_error: {str(e)[:80]}"
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return -1, latency_ms, str(e)[:80]


def _classify(
    status_code: int,
    latency_ms: int,
    warn_ms: int,
    critical_ms: int,
) -> str:
    """Return health classification for a single check."""
    if status_code == -1:
        return "CRITICAL"
    if status_code >= 500:
        return "CRITICAL"
    if status_code >= 400:
        return "WARN"
    if latency_ms >= critical_ms:
        return "CRITICAL"
    if latency_ms >= warn_ms:
        return "WARN"
    return "OK"


def run(**kwargs):
    warn_latency_ms     = int(kwargs.get("warn_latency_ms",     1000))
    critical_latency_ms = int(kwargs.get("critical_latency_ms", 3000))
    check_auth          = bool(kwargs.get("check_auth",         False))
    check_testnet       = bool(kwargs.get("check_testnet",      True))
    alert_on_failure    = bool(kwargs.get("alert_on_failure",   False))
    test_symbol         = kwargs.get("test_symbol",             "BTCUSD")

    now_str  = datetime.now(timezone.utc).isoformat() + "Z"
    messages = []
    results  = {}
    errors   = []

    # ------------------------------------------------------------------
    # Define checks
    # ------------------------------------------------------------------
    checks = [
        {
            "name":    "live_products",
            "url":     f"{_BASE_LIVE}/v2/products",
            "method":  "GET",
            "auth":    False,
            "venue":   "live",
        },
        {
            "name":    "live_tickers",
            "url":     f"{_BASE_LIVE}/v2/tickers?contract_types=perpetual_futures",
            "method":  "GET",
            "auth":    False,
            "venue":   "live",
        },
        {
            "name":    "live_candles",
            "url":     (
                f"{_BASE_LIVE}/v2/history/candles"
                f"?symbol={test_symbol}&resolution=1m&start=1700000000&end=1700003600"
            ),
            "method":  "GET",
            "auth":    False,
            "venue":   "live",
        },
    ]

    if check_testnet:
        checks.append({
            "name":   "testnet_products",
            "url":    f"{_BASE_TESTNET}/v2/products",
            "method": "GET",
            "auth":   False,
            "venue":  "testnet",
        })

    if check_auth:
        import os
        import hashlib
        import hmac

        api_key    = os.getenv("DELTA_LIVE_API_KEY",    "") or os.getenv("DELTA_API_KEY",    "")
        api_secret = os.getenv("DELTA_LIVE_API_SECRET", "") or os.getenv("DELTA_API_SECRET", "")

        if api_key and api_secret:
            ts      = str(int(time.time()))
            path    = "/v2/wallet/balances"
            payload = "GET" + ts + path + "" + ""
            sig     = hmac.new(
                api_secret.encode(),
                payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            auth_headers = {
                "api-key":      api_key,
                "timestamp":    ts,
                "signature":    sig,
                "Content-Type": "application/json",
                "Accept":       "application/json",
            }
            checks.append({
                "name":    "live_auth_balances",
                "url":     f"{_BASE_LIVE}/v2/wallet/balances",
                "method":  "GET",
                "auth":    True,
                "headers": auth_headers,
                "venue":   "live",
            })
        else:
            messages.append(
                "SKIP | live_auth_balances: "
                "no API key configured — skipping auth check"
            )

    # ------------------------------------------------------------------
    # Run all checks
    # ------------------------------------------------------------------
    overall_status = "OK"

    for check in checks:
        headers = check.get("headers", {"Accept": "application/json"})
        status_code, latency_ms, err = _ping(
            check["url"],
            method=check["method"],
            headers=headers,
            timeout=10,
        )
        health = _classify(
            status_code, latency_ms,
            warn_latency_ms, critical_latency_ms,
        )

        results[check["name"]] = {
            "status":      health,
            "status_code": status_code,
            "latency_ms":  latency_ms,
            "error":       err,
            "venue":       check["venue"],
            "checked_at":  now_str,
        }

        if health == "CRITICAL":
            overall_status = "CRITICAL"
        elif health == "WARN" and overall_status == "OK":
            overall_status = "WARN"

        status_str = (
            f"HTTP {status_code}" if status_code > 0
            else f"FAILED ({err})"
        )
        messages.append(
            f"{health:>8} | {check['name']:<25} "
            f"{latency_ms:>6}ms  {status_str}"
        )

    # ------------------------------------------------------------------
    # Persist health status to app_settings
    # ------------------------------------------------------------------
    health_payload = json.dumps({
        "overall":    overall_status,
        "checks":     results,
        "updated_at": now_str,
    })

    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_HEALTH_KEY, health_payload),
            )
    except Exception as e:
        errors.append(f"ERR | app_settings write failed — {e}")

    # ------------------------------------------------------------------
    # Alert on critical failure — pause all live bots
    # ------------------------------------------------------------------
    if overall_status == "CRITICAL" and alert_on_failure:
        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                live_bots = conn.execute(
                    "SELECT id, name FROM deployments "
                    "WHERE status='running' AND venue='live'"
                ).fetchall()

            paused = 0
            for bot in live_bots:
                try:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments SET status='paused' WHERE id=?",
                            (bot["id"],),
                        )
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'api_health_check', ?)",
                            (
                                bot["id"], now_str,
                                f"Paused — API health check CRITICAL. "
                                f"Delta Exchange API may be unreachable or degraded.",
                            ),
                        )
                    paused += 1
                except Exception as e:
                    errors.append(
                        f"ERR | {bot['name']}: pause failed — {e}"
                    )

            if paused > 0:
                messages.append("")
                messages.append(
                    f"CRITICAL ACTION: Paused {paused} live bots "
                    f"due to API health failure."
                )
        except Exception as e:
            errors.append(f"ERR | live bot pause scan failed — {e}")

    elif overall_status == "CRITICAL" and not alert_on_failure:
        messages.append("")
        messages.append(
            "WARNING: API health is CRITICAL. "
            "Set alert_on_failure=true in params_json to automatically "
            "pause live bots during API outages."
        )

    # ------------------------------------------------------------------
    # Build report
    # ------------------------------------------------------------------
    lines = [
        "API Health Check",
        f"  Checked at       : {now_str[:19]} UTC",
        f"  Warn threshold   : {warn_latency_ms}ms",
        f"  Critical threshold: {critical_latency_ms}ms",
        f"  Auth check       : {check_auth}",
        f"  Testnet check    : {check_testnet}",
        "",
        f"OVERALL STATUS: {overall_status}",
        "",
        "Endpoint Results:",
        f"  {'Status':>8}   {'Endpoint':<25} {'Latency':>8}  Response",
        "  " + "-" * 65,
    ]
    lines.extend(f"  {m}" for m in messages
                 if "|" in m and not m.startswith("CRITICAL ACTION"))

    # Latency summary
    ok_checks = [r for r in results.values() if r["status"] == "OK"]
    if ok_checks:
        avg_latency = sum(r["latency_ms"] for r in ok_checks) / len(ok_checks)
        max_latency = max(r["latency_ms"] for r in ok_checks)
        lines.append("")
        lines.append(
            f"Latency Summary (OK checks only): "
            f"avg={avg_latency:.0f}ms  max={max_latency}ms"
        )

    # Action messages
    action_msgs = [m for m in messages if not "|" in m and m.strip()]
    if action_msgs:
        lines.append("")
        lines.extend(action_msgs)

    lines.append("")
    lines.append(
        f"Health status written to app_settings key='{_HEALTH_KEY}'."
    )

    if errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"  {e}" for e in errors)

    return "### API Health Check\n\n" + "\n".join(lines)

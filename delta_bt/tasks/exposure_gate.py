"""Shared exposure gate for auto-deploying hunter tasks.

Blocks NEW deployments while portfolio gross exposure is at/over the
limit configured on the Global Exposure Manager task
(params_json.max_exposure_usd, default 25.0). Existing positions are
never touched — entries simply wait until one closes.

Usage (inside a hunter task, before deploying):

    from delta_bt.tasks.exposure_gate import exposure_blocked
    blocked, reason = exposure_blocked()
    if blocked:
        messages.append(f"> Entry blocked: {reason}")
        continue
"""
from __future__ import annotations

import json
import logging
import sqlite3

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect
from delta_bt.tasks.global_exposure_manager import _get_contract_value, _BASE_URL

logger = logging.getLogger(__name__)

DEFAULT_LIMIT_USD = 25.0


def _configured_limit() -> float:
    """Read max_exposure_usd from the Global Exposure Manager task row."""
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT params_json FROM background_tasks "
                "WHERE script_name='global_exposure_manager' LIMIT 1"
            ).fetchone()
        if row and row[0]:
            return float(json.loads(row[0]).get("max_exposure_usd", DEFAULT_LIMIT_USD))
    except Exception as exc:  # pragma: no cover
        logger.warning("exposure_gate: could not read configured limit: %s", exc)
    return DEFAULT_LIMIT_USD


def gross_exposure_usd() -> float:
    """Gross (long + short) notional across running deployments in position."""
    client = DeltaClient(base_url=_BASE_URL)
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, open_side, open_qty, open_price "
            "FROM deployments WHERE status='running' AND open_side IS NOT NULL"
        ).fetchall()
    gross = 0.0
    for row in rows:
        qty = abs(float(row["open_qty"] or 0))
        price = float(row["open_price"] or 0)
        cv = _get_contract_value(client, row["symbol"])
        gross += qty * price * cv
    return gross


def exposure_blocked(headroom_usd: float = 0.0) -> tuple[bool, str]:
    """Return (True, reason) when new entries must be blocked.

    Fail-open on errors: a broken gate should not silently freeze the
    fleet, and the Global Exposure Manager still runs as backstop.
    """
    try:
        limit = _configured_limit()
        gross = gross_exposure_usd()
        if gross + headroom_usd >= limit:
            return True, (
                f"gross exposure ${gross:,.2f} >= limit ${limit:,.2f} "
                "— waiting for a position to close"
            )
        return False, ""
    except Exception as exc:
        logger.warning("exposure_gate: check failed (%s) — allowing entry", exc)
        return False, ""

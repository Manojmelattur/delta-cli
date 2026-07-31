"""Slippage Tracker Task

Compares the expected entry/exit price stored in deployment_events
against the actual fill price from Delta Exchange order history
to measure real slippage per strategy, symbol, and venue.

High slippage indicates:
  - Poor liquidity on the symbol
  - Market orders filling deep in the book
  - Scheduler tick delay between signal and execution

Produces a per-strategy slippage report and logs findings
to deployment_events for audit trail.

Params (set in task params_json):
    lookback_days        : How many days of order history to fetch (default 7)
    warn_slippage_pct    : Log a warning if avg slippage exceeds this % (default 0.1)
    venue_filter         : Only analyse this venue e.g. "live", "testnet" (default both)
    strategy_filter      : Only analyse this strategy (default all)
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


_BASE_LIVE    = "https://api.india.delta.exchange"
_BASE_TESTNET = "https://cdn-ind.testnet.deltaex.org"


def _client_for(venue: str) -> DeltaClient:
    import os
    if venue == "live":
        base = _BASE_LIVE
        key  = os.getenv("DELTA_LIVE_API_KEY",    "") or os.getenv("DELTA_API_KEY",    "")
        sec  = os.getenv("DELTA_LIVE_API_SECRET", "") or os.getenv("DELTA_API_SECRET", "")
    else:
        base = _BASE_TESTNET
        key  = os.getenv("DELTA_TESTNET_API_KEY",    "") or os.getenv("DELTA_API_KEY",    "")
        sec  = os.getenv("DELTA_TESTNET_API_SECRET", "") or os.getenv("DELTA_API_SECRET", "")
    return DeltaClient(base, key, sec)


def _fetch_fills(client: DeltaClient, since_ts: str) -> List[dict]:
    """Fetch filled orders from Delta Exchange order history.

    Returns list of fill dicts with keys:
        order_id, product_symbol, side, avg_fill_price, size, created_at
    """
    try:
        data = client._request(
            "GET",
            "/v2/orders/history",
            params={
                "states":   "closed",
                "page_size": "100",
            },
            auth=True,
        )
        if isinstance(data, dict):
            data = data.get("result", data)
        if not isinstance(data, list):
            return []
        # Filter to filled orders after since_ts
        fills = []
        for o in data:
            if o.get("state") != "closed":
                continue
            if not o.get("avg_fill_price"):
                continue
            created = o.get("created_at", "")
            if created and created < since_ts:
                continue
            fills.append(o)
        return fills
    except Exception:
        return []


def _calc_slippage_pct(expected: float, actual: float, side: str) -> float:
    """Calculate slippage as a percentage of expected price.

    For a buy: slippage is positive if actual > expected (paid more)
    For a sell: slippage is positive if actual < expected (received less)
    """
    if expected <= 0:
        return 0.0
    if side == "buy":
        return (actual - expected) / expected * 100.0
    return (expected - actual) / expected * 100.0


def run(**kwargs):
    lookback_days     = int(kwargs.get("lookback_days",     7))
    warn_slippage_pct = float(kwargs.get("warn_slippage_pct", 0.1))
    venue_filter      = kwargs.get("venue_filter",          None)
    strategy_filter   = kwargs.get("strategy_filter",       None)

    now_str = datetime.now(timezone.utc).isoformat() + "Z"
    since   = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Fetch entry and exit events with order_id and price
        query = """
            SELECT
                e.id          AS event_id,
                e.deployment_id,
                e.kind,
                e.ts,
                e.price       AS expected_price,
                e.order_id,
                e.side,
                e.qty,
                d.strategy,
                d.symbol,
                d.venue
            FROM deployment_events e
            JOIN deployments d ON e.deployment_id = d.id
            WHERE e.ts       >= ?
              AND e.kind     IN ('entry', 'sl_hit', 'tp_hit',
                                 'signal_exit', 'flip', 'sl_slippage')
              AND e.order_id IS NOT NULL
              AND e.price    IS NOT NULL
        """
        args = [since]

        if venue_filter:
            query += " AND d.venue = ?"
            args.append(venue_filter)
        if strategy_filter:
            query += " AND d.strategy = ?"
            args.append(strategy_filter)

        events = conn.execute(query, args).fetchall()

    if not events:
        return (
            f"Slippage Tracker: No entry/exit events with order IDs "
            f"found in the last {lookback_days} days."
        )

    # Group events by venue to fetch fills per venue
    venue_events: Dict[str, list] = {}
    for ev in events:
        v = ev["venue"]
        if v not in ("live", "testnet"):
            continue  # paper venues have no real fills
        if v not in venue_events:
            venue_events[v] = []
        venue_events[v].append(dict(ev))

    if not venue_events:
        return (
            "Slippage Tracker: No live or testnet events to analyse. "
            "Paper venue orders have no real fill prices."
        )

    # Build order_id -> fill price map per venue
    fill_map: Dict[str, Dict[str, float]] = {}

    for venue, _ in venue_events.items():
        try:
            client = _client_for(venue)
            fills  = _fetch_fills(client, since)
            fill_map[venue] = {
                str(f.get("id") or f.get("order_id", "")): float(
                    f.get("avg_fill_price") or 0
                )
                for f in fills
                if f.get("avg_fill_price")
            }
        except Exception as e:
            fill_map[venue] = {}

    # Calculate slippage per event
    # Aggregate by strategy
    strategy_slippage: Dict[str, dict] = {}
    symbol_slippage:   Dict[str, dict] = {}
    matched   = 0
    unmatched = 0
    warnings  = []

    for venue, evs in venue_events.items():
        fills = fill_map.get(venue, {})

        for ev in evs:
            order_id     = str(ev["order_id"])
            expected_px  = float(ev["expected_price"] or 0)
            side         = ev["side"] or "buy"
            strategy     = ev["strategy"]
            symbol       = ev["symbol"]

            actual_px = fills.get(order_id, 0.0)

            if actual_px <= 0 or expected_px <= 0:
                unmatched += 1
                continue

            slip_pct = _calc_slippage_pct(expected_px, actual_px, side)
            matched += 1

            # Aggregate by strategy
            if strategy not in strategy_slippage:
                strategy_slippage[strategy] = {
                    "count": 0, "total_slip": 0.0,
                    "max_slip": 0.0, "min_slip": 0.0,
                }
            ss = strategy_slippage[strategy]
            ss["count"]      += 1
            ss["total_slip"] += slip_pct
            ss["max_slip"]    = max(ss["max_slip"], slip_pct)
            ss["min_slip"]    = min(ss["min_slip"], slip_pct)

            # Aggregate by symbol
            if symbol not in symbol_slippage:
                symbol_slippage[symbol] = {
                    "count": 0, "total_slip": 0.0,
                    "max_slip": 0.0,
                }
            sym_s = symbol_slippage[symbol]
            sym_s["count"]      += 1
            sym_s["total_slip"] += slip_pct
            sym_s["max_slip"]    = max(sym_s["max_slip"], slip_pct)

            # Warn on high slippage events
            if abs(slip_pct) > warn_slippage_pct:
                warnings.append(
                    f"HIGH SLIPPAGE: {symbol} {side} "
                    f"order={order_id} "
                    f"expected={expected_px:.4f} "
                    f"actual={actual_px:.4f} "
                    f"slip={slip_pct:+.4f}%"
                )
                # Log to deployment_events
                try:
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'slippage_tracker', ?)",
                            (
                                ev["deployment_id"], now_str,
                                f"High slippage detected — "
                                f"expected={expected_px:.4f} "
                                f"actual={actual_px:.4f} "
                                f"slip={slip_pct:+.4f}% "
                                f"(threshold={warn_slippage_pct:.2f}%)",
                            ),
                        )
                except Exception:
                    pass

    # Build report
    lines = [
        f"Slippage Tracker Report",
        f"  Lookback  : {lookback_days} days",
        f"  Events    : {len(events)} total, {matched} matched, {unmatched} unmatched",
        f"  Threshold : {warn_slippage_pct:.2f}%",
        "",
    ]

    if not strategy_slippage:
        lines.append(
            "No fills could be matched to events. "
            "Ensure order_id is being stored in deployment_events."
        )
        return "### Slippage Tracker\n\n" + "\n".join(lines)

    # Strategy breakdown
    lines.append("Slippage by Strategy:")
    lines.append(
        f"  {'Strategy':>20} {'Fills':>6} "
        f"{'Avg Slip%':>10} {'Max Slip%':>10} {'Min Slip%':>10}"
    )
    lines.append("  " + "-" * 60)

    for strat, ss in sorted(
        strategy_slippage.items(),
        key=lambda x: abs(x[1]["total_slip"] / max(x[1]["count"], 1)),
        reverse=True,
    ):
        avg_slip = ss["total_slip"] / ss["count"] if ss["count"] > 0 else 0.0
        flag     = " ***" if abs(avg_slip) > warn_slippage_pct else ""
        lines.append(
            f"  {strat:>20} {ss['count']:>6} "
            f"{avg_slip:>+9.4f}% {ss['max_slip']:>+9.4f}% "
            f"{ss['min_slip']:>+9.4f}%{flag}"
        )

    # Symbol breakdown
    lines.append("")
    lines.append("Slippage by Symbol:")
    lines.append(
        f"  {'Symbol':>12} {'Fills':>6} "
        f"{'Avg Slip%':>10} {'Max Slip%':>10}"
    )
    lines.append("  " + "-" * 42)

    for sym, ss in sorted(
        symbol_slippage.items(),
        key=lambda x: abs(x[1]["total_slip"] / max(x[1]["count"], 1)),
        reverse=True,
    ):
        avg_slip = ss["total_slip"] / ss["count"] if ss["count"] > 0 else 0.0
        flag     = " ***" if abs(avg_slip) > warn_slippage_pct else ""
        lines.append(
            f"  {sym:>12} {ss['count']:>6} "
            f"{avg_slip:>+9.4f}% {ss['max_slip']:>+9.4f}%{flag}"
        )

    # High slippage warnings
    if warnings:
        lines.append("")
        lines.append(f"High Slippage Events ({len(warnings)}):")
        for w in warnings[:20]:  # cap at 20 to avoid huge reports
            lines.append(f"  {w}")
        if len(warnings) > 20:
            lines.append(f"  ... and {len(warnings) - 20} more")

    return "### Slippage Tracker\n\n" + "\n".join(lines)

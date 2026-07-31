"""Deployment Snapshot Task

Takes a daily snapshot of all running deployments and stores it
in a snapshots table for historical comparison and trend analysis.

Each snapshot captures:
  - Bot name, strategy, symbol, venue, resolution
  - Current size, leverage, SL/TP/Trail settings
  - Open position state (side, price, qty)
  - Realized PnL to date
  - Unrealized PnL (from current mark price)
  - Current status and last tick time

Use cases:
  - Track how bot configurations evolve over time
  - Compare PnL growth day over day
  - Audit parameter changes made by auto-tasks
  - Detect configuration drift

The snapshots table is created automatically if it does not exist.

Params (set in task params_json):
    include_paused    : Also snapshot paused bots (default True)
    include_paper     : Include paper venue bots (default True)
    include_live      : Include live venue bots (default True)
    include_testnet   : Include testnet venue bots (default True)
    capture_mark_price: Fetch live mark price for unrealized PnL (default True)
    retention_days    : Delete snapshots older than this (default 365)
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


_BASE_LIVE    = "https://api.india.delta.exchange"
_BASE_TESTNET = "https://cdn-ind.testnet.deltaex.org"


def _ensure_snapshots_table(conn) -> None:
    """Create the deployment_snapshots table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS deployment_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date   TEXT    NOT NULL,
            deployment_id   INTEGER NOT NULL,
            name            TEXT,
            strategy        TEXT,
            symbol          TEXT,
            venue           TEXT,
            resolution      TEXT,
            size            REAL,
            leverage        REAL,
            sl_pct          REAL,
            tp_pct          REAL,
            trail_pct       REAL,
            trail_activate_pct  REAL,
            breakeven_after_pct REAL,
            status          TEXT,
            open_side       TEXT,
            open_price      REAL,
            open_qty        REAL,
            realized_pnl    REAL,
            unrealized_pnl  REAL,
            mark_price      REAL,
            last_tick_at    TEXT,
            params_json     TEXT,
            tag             TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snapshots_date
        ON deployment_snapshots(snapshot_date)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snapshots_deployment
        ON deployment_snapshots(deployment_id, snapshot_date)
        """
    )


def _get_mark_price(
    client: DeltaClient,
    symbol: str,
) -> float:
    """Fetch current mark price for a symbol. Returns 0.0 on failure."""
    try:
        ticker = client.ticker(symbol)
        return float(ticker.get("mark_price") or ticker.get("close") or 0)
    except Exception:
        return 0.0


def _calc_unrealized_pnl(
    open_side: str,
    open_price: float,
    mark_price: float,
    open_qty: float,
    contract_value: float,
) -> float:
    """Calculate unrealized PnL for an open position."""
    if not open_side or not open_price or not mark_price or not open_qty:
        return 0.0
    if open_side == "buy":
        return (mark_price - open_price) * open_qty * contract_value
    return (open_price - mark_price) * open_qty * contract_value


def _get_contract_value(client: DeltaClient, symbol: str) -> float:
    """Fetch contract value with fallback to 1.0."""
    try:
        prod = client.get_product(symbol)
        return float(prod.get("contract_value") or 1) or 1.0
    except Exception:
        return 1.0


def run(**kwargs):
    include_paused     = bool(kwargs.get("include_paused",     True))
    include_paper      = bool(kwargs.get("include_paper",      True))
    include_live       = bool(kwargs.get("include_live",       True))
    include_testnet    = bool(kwargs.get("include_testnet",    True))
    capture_mark_price = bool(kwargs.get("capture_mark_price", True))
    retention_days     = int(kwargs.get("retention_days",      365))

    now        = datetime.now(timezone.utc)
    now_str    = now.isoformat() + "Z"
    today      = now.strftime("%Y-%m-%d")
    cutoff     = (now - timedelta(days=retention_days)).isoformat() + "Z"

    # Build venue filter
    allowed_venues = []
    if include_paper:
        allowed_venues.extend(["paper", "paper_live"])
    if include_live:
        allowed_venues.append("live")
    if include_testnet:
        allowed_venues.append("testnet")

    if not allowed_venues:
        return "Deployment Snapshot: No venues selected — nothing to snapshot."

    # Build status filter
    status_filter = ["running"]
    if include_paused:
        status_filter.append("paused")

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Ensure snapshots table exists
        _ensure_snapshots_table(conn)

        # Check if we already have a snapshot for today
        existing = conn.execute(
            "SELECT COUNT(*) AS cnt FROM deployment_snapshots "
            "WHERE snapshot_date = ?",
            (today,),
        ).fetchone()

        if existing and int(existing["cnt"]) > 0:
            return (
                f"Deployment Snapshot: Snapshot for {today} already exists "
                f"({existing['cnt']} rows). Skipping duplicate snapshot."
            )

        # Fetch deployments to snapshot
        venue_placeholders  = ",".join(["?"] * len(allowed_venues))
        status_placeholders = ",".join(["?"] * len(status_filter))

        rows = conn.execute(
            f"""
            SELECT
                id, name, strategy, symbol, venue, resolution,
                size, leverage, sl_pct, tp_pct, trail_pct,
                trail_activate_pct, breakeven_after_pct,
                status, open_side, open_price, open_qty,
                realized_pnl, last_tick_at, params_json, tag
            FROM deployments
            WHERE venue  IN ({venue_placeholders})
              AND status IN ({status_placeholders})
            """,
            [*allowed_venues, *status_filter],
        ).fetchall()

    if not rows:
        return (
            f"Deployment Snapshot: No deployments found matching "
            f"venue/status filters for {today}."
        )

    # Build mark price clients per venue
    live_client    = DeltaClient(base_url=_BASE_LIVE)    if capture_mark_price else None
    testnet_client = DeltaClient(base_url=_BASE_TESTNET) if capture_mark_price else None

    # Cache contract values per symbol to avoid repeated API calls
    cv_cache: dict = {}

    def _get_cv(symbol: str, venue: str) -> float:
        key = f"{venue}:{symbol}"
        if key in cv_cache:
            return cv_cache[key]
        client = live_client if venue != "testnet" else testnet_client
        cv = _get_contract_value(client, symbol) if client else 1.0
        cv_cache[key] = cv
        return cv

    # Take snapshots
    snapshots  = []
    errors     = []

    for row in rows:
        dep_id     = row["id"]
        symbol     = row["symbol"]
        venue      = row["venue"]
        open_side  = row["open_side"]
        open_price = float(row["open_price"] or 0)
        open_qty   = float(row["open_qty"]   or 0)

        # Fetch mark price for unrealized PnL
        mark_price     = 0.0
        unrealized_pnl = 0.0

        if capture_mark_price and open_side and open_price and open_qty:
            try:
                client = (
                    testnet_client
                    if venue == "testnet"
                    else live_client
                )
                if client:
                    mark_price = _get_mark_price(client, symbol)
                    if mark_price > 0:
                        cv = _get_cv(symbol, venue)
                        unrealized_pnl = _calc_unrealized_pnl(
                            open_side, open_price,
                            mark_price, open_qty, cv,
                        )
            except Exception as e:
                errors.append(
                    f"WARN | {row['name']} ({symbol}): "
                    f"mark price fetch failed — {e}"
                )

        snapshots.append((
            today,
            dep_id,
            row["name"],
            row["strategy"],
            symbol,
            venue,
            row["resolution"],
            float(row["size"]     or 0),
            float(row["leverage"] or 1),
            float(row["sl_pct"]   or 0),
            float(row["tp_pct"]   or 0),
            float(row["trail_pct"] or 0),
            float(row["trail_activate_pct"]  or 0),
            float(row["breakeven_after_pct"] or 0),
            row["status"],
            open_side,
            open_price,
            open_qty,
            float(row["realized_pnl"] or 0),
            round(unrealized_pnl, 6),
            mark_price,
            row["last_tick_at"],
            row["params_json"],
            row["tag"],
        ))

    # Bulk insert all snapshots
    inserted = 0
    try:
        with connect() as conn:
            _ensure_snapshots_table(conn)
            conn.executemany(
                """
                INSERT INTO deployment_snapshots (
                    snapshot_date, deployment_id, name, strategy,
                    symbol, venue, resolution, size, leverage,
                    sl_pct, tp_pct, trail_pct, trail_activate_pct,
                    breakeven_after_pct, status, open_side, open_price,
                    open_qty, realized_pnl, unrealized_pnl, mark_price,
                    last_tick_at, params_json, tag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                snapshots,
            )
            inserted = len(snapshots)
    except Exception as e:
        errors.append(f"ERR | snapshot insert failed — {e}")

    # Delete old snapshots beyond retention window
    deleted_old = 0
    try:
        with connect() as conn:
            result = conn.execute(
                "DELETE FROM deployment_snapshots WHERE created_at < ?",
                (cutoff,),
            )
            deleted_old = result.rowcount if hasattr(result, "rowcount") else 0
    except Exception as e:
        errors.append(f"WARN | old snapshot cleanup failed — {e}")

    # Compare with yesterday's snapshot for PnL delta
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    pnl_deltas = []

    try:
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            yesterday_snaps = conn.execute(
                """
                SELECT deployment_id, name, realized_pnl
                FROM deployment_snapshots
                WHERE snapshot_date = ?
                """,
                (yesterday,),
            ).fetchall()

            today_snaps = conn.execute(
                """
                SELECT deployment_id, name, realized_pnl, unrealized_pnl
                FROM deployment_snapshots
                WHERE snapshot_date = ?
                """,
                (today,),
            ).fetchall()

        yesterday_map = {
            r["deployment_id"]: float(r["realized_pnl"] or 0)
            for r in yesterday_snaps
        }
        for snap in today_snaps:
            dep_id    = snap["deployment_id"]
            today_pnl = float(snap["realized_pnl"]    or 0)
            upnl      = float(snap["unrealized_pnl"]  or 0)
            if dep_id in yesterday_map:
                delta = today_pnl - yesterday_map[dep_id]
                if abs(delta) > 0.0001:
                    pnl_deltas.append({
                        "name":  snap["name"],
                        "delta": delta,
                        "upnl":  upnl,
                    })
    except Exception as e:
        errors.append(f"WARN | PnL delta comparison failed — {e}")

    # Build report
    total_realized   = sum(float(r["realized_pnl"] or 0) for r in rows)
    total_unrealized = sum(s[19] for s in snapshots)  # unrealized_pnl index
    in_position      = sum(1 for r in rows if r["open_side"])
    flat_bots        = sum(1 for r in rows if not r["open_side"])

    lines = [
        f"Deployment Snapshot — {today}",
        f"  Bots snapshotted : {inserted}",
        f"  In position      : {in_position}",
        f"  Flat             : {flat_bots}",
        f"  Total Realized   : ${total_realized:.2f}",
        f"  Total Unrealized : ${total_unrealized:.2f}",
        f"  Total PnL        : ${total_realized + total_unrealized:.2f}",
        f"  Old snapshots del: {deleted_old}",
        f"  Retention        : {retention_days} days",
        "",
    ]

    # Venue breakdown
    venue_counts: dict = {}
    for r in rows:
        v = r["venue"]
        venue_counts[v] = venue_counts.get(v, 0) + 1

    lines.append("Venue Breakdown:")
    for v, cnt in sorted(venue_counts.items()):
        lines.append(f"  {v:<12}: {cnt} bots")
    lines.append("")

    # Day-over-day PnL changes
    if pnl_deltas:
        lines.append("Day-over-Day PnL Changes (vs yesterday):")
        for d in sorted(pnl_deltas, key=lambda x: abs(x["delta"]), reverse=True)[:10]:
            sign = "+" if d["delta"] >= 0 else ""
            lines.append(
                f"  {d['name']:<30} "
                f"realized {sign}${d['delta']:.4f}  "
                f"unrealized ${d['upnl']:.4f}"
            )
        lines.append("")
    else:
        lines.append(
            f"Day-over-Day: No yesterday snapshot found for comparison "
            f"(date={yesterday})."
        )
        lines.append("")

    lines.append(
        f"Snapshot stored in deployment_snapshots table. "
        f"Query with: SELECT * FROM deployment_snapshots "
        f"WHERE snapshot_date='{today}'"
    )

    if errors:
        lines.append("")
        lines.append("Warnings/Errors:")
        lines.extend(f"  {e}" for e in errors)

    return "### Deployment Snapshot\n\n" + "\n".join(lines)

"""Duplicate Position Guard Task

Detects if multiple bots have open positions on the same symbol
in the same direction. Prevents unintended over-exposure caused
by multiple auto-deployed bots entering the same trade simultaneously.

Actions taken when duplicates are detected:
  - Logs a warning event on each duplicate deployment
  - If auto_close=True, issues FLAT signal to all but the oldest position
    (keeps the first entry, closes the newer duplicates)

Params (set in task params_json):
    auto_close     : If True, closes duplicate positions (default False)
    venue_filter   : Only check this venue e.g. "live", "paper" (default all)
    tag_filter     : Only check bots with this tag (default all)
    keep_strategy  : If set, always keep this strategy and close others
"""
import sqlite3
from datetime import datetime, timezone

from delta_bt.store.db import connect


def run(**kwargs):
    auto_close     = bool(kwargs.get("auto_close",    False))
    venue_filter   = kwargs.get("venue_filter",       None)
    tag_filter     = kwargs.get("tag_filter",         None)
    keep_strategy  = kwargs.get("keep_strategy",      None)

    now_str = datetime.now(timezone.utc).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Fetch all running deployments with an open position
        query = """
            SELECT
                d.id,
                d.name,
                d.symbol,
                d.venue,
                d.strategy,
                d.open_side,
                d.open_qty,
                d.open_price,
                d.tag,
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
            WHERE d.status  = 'running'
              AND d.open_side IS NOT NULL
              AND d.open_qty  IS NOT NULL
        """
        args = []
        if venue_filter:
            query += " AND d.venue = ?"
            args.append(venue_filter)
        if tag_filter:
            query += " AND d.tag = ?"
            args.append(tag_filter)

        rows = conn.execute(query, args).fetchall()

    if not rows:
        return "Duplicate Position Guard: No open positions to check."

    # Group positions by (symbol, open_side)
    groups: dict = {}
    for row in rows:
        key = (row["symbol"], row["open_side"])
        if key not in groups:
            groups[key] = []
        groups[key].append(dict(row))

    messages  = []
    checked   = len(rows)
    warned    = 0
    closed    = 0
    errors    = []

    for (symbol, side), positions in groups.items():
        if len(positions) < 2:
            # No duplicate — skip
            continue

        total_qty = sum(float(p["open_qty"] or 0) for p in positions)
        messages.append(
            f"DUPLICATE DETECTED: {len(positions)} bots have "
            f"{side.upper()} positions on {symbol} "
            f"(total qty={total_qty:.2f})"
        )

        for p in positions:
            messages.append(
                f"  Bot #{p['id']} {p['name']} "
                f"({p['strategy']}) "
                f"qty={p['open_qty']} "
                f"@ {p['open_price']} "
                f"entry={p['entry_ts'] or 'unknown'} "
                f"tag={p['tag'] or 'none'}"
            )

        # Determine which position to keep
        # Priority: keep_strategy > oldest entry timestamp > lowest id
        if keep_strategy:
            keeper = next(
                (p for p in positions if p["strategy"] == keep_strategy),
                None,
            )
            if not keeper:
                # keep_strategy not found — fall back to oldest
                keeper = _pick_oldest(positions)
        else:
            keeper = _pick_oldest(positions)

        duplicates = [p for p in positions if p["id"] != keeper["id"]]

        messages.append(
            f"  Keeping : Bot #{keeper['id']} {keeper['name']} "
            f"({keeper['strategy']}) entry={keeper['entry_ts'] or 'unknown'}"
        )

        for dup in duplicates:
            # Log warning event on each duplicate
            try:
                with connect() as conn:
                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'duplicate_position_guard', ?)",
                        (
                            dup["id"], now_str,
                            f"Duplicate {side} position on {symbol} detected — "
                            f"{len(positions)} bots in same direction. "
                            f"Keeper=#{keeper['id']} {keeper['name']}",
                        ),
                    )
                warned += 1
            except Exception as e:
                errors.append(
                    f"ERR | Bot #{dup['id']} {dup['name']}: "
                    f"event log failed — {e}"
                )

            if auto_close:
                try:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE deployments "
                            "SET signal_override='FLAT' WHERE id=?",
                            (dup["id"],),
                        )
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'duplicate_position_guard', ?)",
                            (
                                dup["id"], now_str,
                                f"FLAT signal issued — duplicate {side} "
                                f"position on {symbol} closed. "
                                f"Keeper=#{keeper['id']} {keeper['name']}",
                            ),
                        )
                    messages.append(
                        f"  Closed  : Bot #{dup['id']} {dup['name']} "
                        f"— FLAT signal issued."
                    )
                    closed += 1
                except Exception as e:
                    err = (
                        f"ERR | Bot #{dup['id']} {dup['name']}: "
                        f"close failed — {e}"
                    )
                    errors.append(err)
                    messages.append(f"  {err}")
            else:
                messages.append(
                    f"  Warned  : Bot #{dup['id']} {dup['name']} "
                    f"— auto_close=False, no action taken."
                )

    if not messages:
        return (
            f"Duplicate Position Guard: All {checked} open positions "
            f"are unique (no symbol+direction duplicates found)."
        )

    summary = (
        f"Duplicate Position Guard complete — "
        f"checked={checked}, "
        f"duplicates_warned={warned}, "
        f"closed={closed}"
    )
    messages.insert(0, summary)

    if not auto_close:
        messages.append(
            "Note: Set auto_close=true in params_json to automatically "
            "close duplicate positions."
        )

    if errors:
        messages.append("Errors:")
        messages.extend(errors)

    return "### Duplicate Position Guard\n\n" + "\n".join(messages)


def _pick_oldest(positions: list) -> dict:
    """Return the position with the earliest entry timestamp.

    Falls back to lowest deployment ID if timestamps are missing or equal.
    """
    def sort_key(p):
        ts = p.get("entry_ts") or ""
        return (ts, p["id"])

    return sorted(positions, key=sort_key)[0]

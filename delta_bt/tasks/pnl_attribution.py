"""PnL Attribution Task

Breaks down realized PnL by strategy, venue, resolution, symbol,
and tag to produce a full multi-dimensional attribution report.

Helps answer:
  - Which strategy is making the most money?
  - Is paper outperforming live?
  - Which resolution (15m vs 1h) is most profitable?
  - Which auto-deploy tag generates the best returns?
  - Which symbols are winners vs losers?

Params (set in task params_json):
    lookback_days    : How many days of history to analyse (default 30)
    min_trades       : Minimum trades to include a bucket (default 1)
    venue_filter     : Only analyse this venue (default all)
    strategy_filter  : Only analyse this strategy (default all)
    top_n            : Number of top/bottom items to highlight (default 5)
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict

from delta_bt.store.db import connect


def _build_bucket(rows) -> dict:
    """Aggregate a list of sqlite3.Row trade events into a stats bucket."""
    trades    = 0
    wins      = 0
    losses    = 0
    total_pnl = 0.0
    best      = None
    worst     = None

    for row in rows:
        pnl = float(row["pnl"] or 0.0)
        trades    += 1
        total_pnl += pnl
        if pnl > 0:
            wins += 1
        else:
            losses += 1
        if best  is None or pnl > best:
            best  = pnl
        if worst is None or pnl < worst:
            worst = pnl

    win_rate  = (wins / trades * 100) if trades > 0 else 0.0
    avg_pnl   = (total_pnl / trades)  if trades > 0 else 0.0

    return {
        "trades":    trades,
        "wins":      wins,
        "losses":    losses,
        "win_rate":  win_rate,
        "total_pnl": total_pnl,
        "avg_pnl":   avg_pnl,
        "best":      best  or 0.0,
        "worst":     worst or 0.0,
    }


def _format_bucket_row(
    label: str,
    b: dict,
    label_width: int = 20,
) -> str:
    """Format a single attribution row for the report table."""
    return (
        f"  {label:<{label_width}} "
        f"{b['trades']:>7} "
        f"{b['wins']:>5} "
        f"{b['losses']:>7} "
        f"{b['win_rate']:>6.1f}% "
        f"${b['total_pnl']:>10.2f} "
        f"${b['avg_pnl']:>8.4f} "
        f"${b['best']:>8.4f} "
        f"${b['worst']:>9.4f}"
    )


def _table_header(label_width: int = 20) -> list:
    """Return header lines for the attribution table."""
    return [
        f"  {'Bucket':<{label_width}} "
        f"{'Trades':>7} "
        f"{'Wins':>5} "
        f"{'Losses':>7} "
        f"{'WR%':>7} "
        f"{'Total PnL':>11} "
        f"{'Avg PnL':>9} "
        f"{'Best':>9} "
        f"{'Worst':>10}",
        "  " + "-" * 85,
    ]


def run(**kwargs):
    lookback_days   = int(kwargs.get("lookback_days",   30))
    min_trades      = int(kwargs.get("min_trades",      1))
    venue_filter    = kwargs.get("venue_filter",        None)
    strategy_filter = kwargs.get("strategy_filter",     None)
    top_n           = int(kwargs.get("top_n",           5))

    since = (
        datetime.now(timezone.utc) - timedelta(days=lookback_days)
    ).isoformat() + "Z"

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # Fetch all closed trade events with deployment metadata
        query = """
            SELECT
                e.pnl,
                e.ts,
                e.kind,
                d.strategy,
                d.venue,
                d.resolution,
                d.symbol,
                d.tag
            FROM deployment_events e
            JOIN deployments d ON e.deployment_id = d.id
            WHERE e.ts    >= ?
              AND e.pnl   IS NOT NULL
              AND e.kind  IN (
                  'sl_hit', 'tp_hit', 'signal_exit',
                  'flip', 'sl_slippage', 'exchange_sync_close'
              )
        """
        args = [since]

        if venue_filter:
            query += " AND d.venue = ?"
            args.append(venue_filter)
        if strategy_filter:
            query += " AND d.strategy = ?"
            args.append(strategy_filter)

        query += " ORDER BY e.ts ASC"
        rows = conn.execute(query, args).fetchall()

    if not rows:
        return (
            f"PnL Attribution: No closed trade events found "
            f"in the last {lookback_days} days."
        )

    # ------------------------------------------------------------------
    # Build attribution buckets
    # ------------------------------------------------------------------
    by_strategy:   Dict[str, list] = {}
    by_venue:      Dict[str, list] = {}
    by_resolution: Dict[str, list] = {}
    by_symbol:     Dict[str, list] = {}
    by_tag:        Dict[str, list] = {}
    by_exit_kind:  Dict[str, list] = {}

    for row in rows:
        strat  = row["strategy"]   or "unknown"
        venue  = row["venue"]      or "unknown"
        res    = row["resolution"] or "unknown"
        sym    = row["symbol"]     or "unknown"
        tag    = row["tag"]        or "untagged"
        kind   = row["kind"]       or "unknown"

        for bucket, key in [
            (by_strategy,   strat),
            (by_venue,      venue),
            (by_resolution, res),
            (by_symbol,     sym),
            (by_tag,        tag),
            (by_exit_kind,  kind),
        ]:
            if key not in bucket:
                bucket[key] = []
            bucket[key].append(row)

    # ------------------------------------------------------------------
    # Build overall stats
    # ------------------------------------------------------------------
    overall = _build_bucket(rows)

    # ------------------------------------------------------------------
    # Build report
    # ------------------------------------------------------------------
    filters = []
    if venue_filter:    filters.append(f"venue={venue_filter}")
    if strategy_filter: filters.append(f"strategy={strategy_filter}")
    filter_str = ", ".join(filters) if filters else "all"

    lines = [
        "PnL Attribution Report",
        f"  Lookback : {lookback_days} days",
        f"  Filters  : {filter_str}",
        f"  Events   : {len(rows)} closed trades",
        "",
        "Overall:",
        *_table_header(),
        _format_bucket_row("TOTAL", overall),
        "",
    ]

    # ------------------------------------------------------------------
    # By Strategy
    # ------------------------------------------------------------------
    lines.append("By Strategy:")
    lines.extend(_table_header())
    strat_buckets = {
        k: _build_bucket(v)
        for k, v in by_strategy.items()
        if _build_bucket(v)["trades"] >= min_trades
    }
    for label, b in sorted(
        strat_buckets.items(),
        key=lambda x: x[1]["total_pnl"],
        reverse=True,
    ):
        lines.append(_format_bucket_row(label, b))
    lines.append("")

    # ------------------------------------------------------------------
    # By Venue
    # ------------------------------------------------------------------
    lines.append("By Venue:")
    lines.extend(_table_header())
    for label, evs in sorted(by_venue.items()):
        b = _build_bucket(evs)
        if b["trades"] >= min_trades:
            lines.append(_format_bucket_row(label, b))
    lines.append("")

    # ------------------------------------------------------------------
    # By Resolution
    # ------------------------------------------------------------------
    res_order = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
    lines.append("By Resolution:")
    lines.extend(_table_header())
    sorted_res = sorted(
        by_resolution.items(),
        key=lambda x: res_order.index(x[0])
        if x[0] in res_order else 99,
    )
    for label, evs in sorted_res:
        b = _build_bucket(evs)
        if b["trades"] >= min_trades:
            lines.append(_format_bucket_row(label, b))
    lines.append("")

    # ------------------------------------------------------------------
    # By Tag
    # ------------------------------------------------------------------
    lines.append("By Tag (Auto-Deploy Source):")
    lines.extend(_table_header())
    tag_buckets = {
        k: _build_bucket(v)
        for k, v in by_tag.items()
        if _build_bucket(v)["trades"] >= min_trades
    }
    for label, b in sorted(
        tag_buckets.items(),
        key=lambda x: x[1]["total_pnl"],
        reverse=True,
    ):
        lines.append(_format_bucket_row(label, b))
    lines.append("")

    # ------------------------------------------------------------------
    # By Exit Kind
    # ------------------------------------------------------------------
    lines.append("By Exit Type:")
    lines.extend(_table_header())
    for label, evs in sorted(by_exit_kind.items()):
        b = _build_bucket(evs)
        if b["trades"] >= min_trades:
            lines.append(_format_bucket_row(label, b))
    lines.append("")

    # ------------------------------------------------------------------
    # Top and Bottom Symbols
    # ------------------------------------------------------------------
    sym_buckets = {
        k: _build_bucket(v)
        for k, v in by_symbol.items()
        if _build_bucket(v)["trades"] >= min_trades
    }
    sorted_syms = sorted(
        sym_buckets.items(),
        key=lambda x: x[1]["total_pnl"],
        reverse=True,
    )

    lines.append(f"Top {top_n} Symbols by PnL:")
    lines.extend(_table_header(label_width=12))
    for label, b in sorted_syms[:top_n]:
        lines.append(_format_bucket_row(label, b, label_width=12))
    lines.append("")

    lines.append(f"Bottom {top_n} Symbols by PnL:")
    lines.extend(_table_header(label_width=12))
    for label, b in sorted_syms[-top_n:]:
        lines.append(_format_bucket_row(label, b, label_width=12))
    lines.append("")

    # ------------------------------------------------------------------
    # Key Insights
    # ------------------------------------------------------------------
    insights = []

    if strat_buckets:
        best_strat  = max(strat_buckets.items(), key=lambda x: x[1]["total_pnl"])
        worst_strat = min(strat_buckets.items(), key=lambda x: x[1]["total_pnl"])
        insights.append(
            f"Best strategy  : {best_strat[0]} "
            f"(${best_strat[1]['total_pnl']:.2f} "
            f"WR={best_strat[1]['win_rate']:.1f}%)"
        )
        insights.append(
            f"Worst strategy : {worst_strat[0]} "
            f"(${worst_strat[1]['total_pnl']:.2f} "
            f"WR={worst_strat[1]['win_rate']:.1f}%)"
        )

    if tag_buckets:
        best_tag = max(tag_buckets.items(), key=lambda x: x[1]["total_pnl"])
        insights.append(
            f"Best tag       : {best_tag[0]} "
            f"(${best_tag[1]['total_pnl']:.2f} "
            f"WR={best_tag[1]['win_rate']:.1f}%)"
        )

    if sym_buckets:
        best_sym  = sorted_syms[0]
        worst_sym = sorted_syms[-1]
        insights.append(
            f"Best symbol    : {best_sym[0]} "
            f"(${best_sym[1]['total_pnl']:.2f})"
        )
        insights.append(
            f"Worst symbol   : {worst_sym[0]} "
            f"(${worst_sym[1]['total_pnl']:.2f})"
        )

    if insights:
        lines.append("Key Insights:")
        for insight in insights:
            lines.append(f"  {insight}")

    return "### PnL Attribution Report\n\n" + "\n".join(lines)

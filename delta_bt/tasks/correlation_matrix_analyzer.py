import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


# Fix 4: removed unused `import math` — using ** 0.5 instead of math.sqrt
def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """Calculate Pearson correlation coefficient between two return series."""
    n = min(len(x), len(y))
    if n < 10:
        return 0.0
    x, y = x[:n], y[:n]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    var_x = sum((a - mean_x) ** 2 for a in x)
    var_y = sum((b - mean_y) ** 2 for b in y)
    cov   = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))

    if var_x <= 0 or var_y <= 0:
        return 0.0

    # Fix 4: (var_x * var_y) ** 0.5 replaces math.sqrt
    return cov / (var_x * var_y) ** 0.5


def run(**kwargs):
    """
    Portfolio Correlation and Beta Matrix Task.
    Calculates rolling price return correlation across active deployment symbols
    to warn against over-concentration risk.
    """
    warning_threshold = float(kwargs.get("warning_threshold", 0.85))
    # Fix 6: configurable lookback window
    lookback_days     = int(kwargs.get("lookback_days", 14))

    with connect() as conn:
        conn.row_factory = sqlite3.Row  # Fix 5: named column access
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM deployments WHERE status='running'"
        ).fetchall()

    symbols = [r["symbol"] for r in rows if r["symbol"]]

    if len(symbols) < 2:
        return (
            "Correlation Matrix Analyzer: Need at least 2 active symbols "
            "to compute correlation matrix."
        )

    # Fix 1: correct base URL
    client     = DeltaClient(base_url="https://api.india.delta.exchange")
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=lookback_days)

    returns_map: Dict[str, List[float]] = {}
    fetch_errors = []

    for sym in symbols:
        try:
            bars = client.candles(sym, "1h", start_time, end_time)
            if not bars or len(bars) < 10:
                fetch_errors.append(f"WARN | {sym}: insufficient bars ({len(bars) if bars else 0})")
                continue

            # Fix 2: client.candles() returns dicts — use key access not attributes
            rets = [
                (float(bars[i]["close"]) - float(bars[i - 1]["close"]))
                / float(bars[i - 1]["close"])
                for i in range(1, len(bars))
                if float(bars[i - 1]["close"]) != 0
            ]
            if rets:
                returns_map[sym] = rets

        # Fix 3: log errors instead of silently continuing
        except Exception as e:
            fetch_errors.append(f"ERR | {sym}: {e}")

    valid_syms = list(returns_map.keys())

    if len(valid_syms) < 2:
        err_detail = "\n".join(fetch_errors) if fetch_errors else "No detail available."
        return (
            f"Correlation Matrix Analyzer: Could not fetch enough data "
            f"for correlation analysis.\n{err_detail}"
        )

    high_corrs  = []
    all_corrs   = []

    for i in range(len(valid_syms)):
        for j in range(i + 1, len(valid_syms)):
            s1, s2 = valid_syms[i], valid_syms[j]
            corr   = _pearson_correlation(returns_map[s1], returns_map[s2])
            all_corrs.append((s1, s2, corr))
            if corr >= warning_threshold:
                high_corrs.append((s1, s2, corr))

    # Fix 7: log high correlation findings to deployment_events for audit trail
    if high_corrs:
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                for s1, s2, corr in high_corrs:
                    # Log against each deployment involved in the high correlation
                    dep_rows = conn.execute(
                        "SELECT id FROM deployments "
                        "WHERE symbol IN (?, ?) AND status='running'",
                        (s1, s2),
                    ).fetchall()
                    for dep in dep_rows:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'correlation_warning', ?)",
                            (
                                dep["id"], now_str,
                                f"High correlation {corr:.2f} detected between "
                                f"{s1} and {s2} (threshold={warning_threshold})",
                            ),
                        )
        except Exception as e:
            fetch_errors.append(f"WARN: event log failed — {e}")

    # Build report
    lines = [
        f"Portfolio Correlation Matrix "
        f"({lookback_days}d lookback, {len(valid_syms)} symbols, "
        f"threshold={warning_threshold}):"
    ]

    if fetch_errors:
        lines.append("\nData Warnings:")
        lines.extend(fetch_errors)

    if not high_corrs:
        lines.append(
            f"\nAll {len(all_corrs)} pairs are well-diversified "
            f"(no correlations >= {warning_threshold})."
        )
    else:
        lines.append(
            f"\nHigh Correlation Warnings ({len(high_corrs)} pairs):"
        )
        # Sort by correlation descending
        for s1, s2, corr in sorted(high_corrs, key=lambda x: x[2], reverse=True):
            lines.append(
                f"  {s1} <-> {s2}: {corr:.3f} "
                f"(high directional co-movement risk)"
            )

        lines.append(
            f"\nAll Pairs ({len(all_corrs)} total):"
        )
        for s1, s2, corr in sorted(all_corrs, key=lambda x: x[2], reverse=True):
            flag = " *** HIGH ***" if corr >= warning_threshold else ""
            lines.append(f"  {s1} <-> {s2}: {corr:.3f}{flag}")

    return "\n".join(lines)

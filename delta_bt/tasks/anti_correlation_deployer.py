"""Anti-Correlation Deployer Task

Before auto-deploying a new bot, checks the Pearson correlation
between the candidate symbol and all currently open positions.

Only deploys if the candidate symbol has low correlation with
existing positions — preventing the portfolio from becoming
a single concentrated bet dressed up as multiple bots.

How it works:
  1. Reads pending_deployments table for bots queued for deployment
  2. Fetches 1h return series for the candidate and all open symbols
  3. Calculates Pearson correlation between candidate and each open symbol
  4. Deploys only if max correlation is below max_correlation threshold
  5. Logs decision (deploy/reject) to deployment_events

The pending_deployments table is populated by scanner tasks
(keltner_hunter, smc_hunter etc.) when auto_deploy=False but
queue_if_correlated=True is set in their params.

Alternatively this task can be used as a standalone filter
by calling it directly with a symbol list in params_json.

Params (set in task params_json):
    max_correlation      : Max allowed correlation with open positions (default 0.7)
    lookback_hours       : Hours of 1h candles for correlation (default 48)
    min_bars             : Minimum bars required for correlation (default 24)
    symbols_to_check     : List of symbols to evaluate for deployment
                           If not set, reads from pending_deployments table
    strategy             : Strategy to deploy if correlation passes (default ema3)
    venue                : Venue to deploy on (default paper)
    base_lot_size        : Lot size for new deployments (default 1.0)
    resolution           : Resolution for new deployments (default 15m)
    sl_pct               : SL for new deployments (default 2.0)
    tp_pct               : TP for new deployments (default 0.0)
    trail_pct            : Trail for new deployments (default 1.0)
    trail_activate_pct   : Trail activation for new deployments (default 1.0)
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.store.db import connect


_BASE_URL = "https://api.india.delta.exchange"


def _pearson(x: List[float], y: List[float]) -> float:
    """Calculate Pearson correlation coefficient."""
    n = min(len(x), len(y))
    if n < 10:
        return 0.0
    x, y = x[:n], y[:n]

    mean_x = sum(x) / n
    mean_y = sum(y) / n
    var_x  = sum((a - mean_x) ** 2 for a in x)
    var_y  = sum((b - mean_y) ** 2 for b in y)
    cov    = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))

    if var_x <= 0 or var_y <= 0:
        return 0.0
    return cov / (var_x * var_y) ** 0.5


def _returns(bars) -> List[float]:
    """Calculate log returns from a list of Bar objects."""
    closes = [float(b.close) for b in bars]
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def _fetch_returns(
    client: DeltaClient,
    symbol: str,
    start_time,
    end_time,
    min_bars: int,
) -> Optional[List[float]]:
    """Fetch bars and compute returns. Returns None if insufficient data."""
    try:
        bars = load_history(client, symbol, "1h", start_time, end_time)
        if not bars or len(bars) < min_bars:
            return None
        return _returns(bars)
    except Exception:
        return None


def _ensure_pending_table(conn) -> None:
    """Create pending_deployments table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_deployments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol       TEXT    NOT NULL,
            strategy     TEXT    NOT NULL,
            resolution   TEXT    DEFAULT '15m',
            venue        TEXT    DEFAULT 'paper',
            size         REAL    DEFAULT 1.0,
            params_json  TEXT    DEFAULT '{}',
            sl_pct       REAL    DEFAULT 2.0,
            tp_pct       REAL    DEFAULT 0.0,
            trail_pct    REAL    DEFAULT 1.0,
            trail_activate_pct REAL DEFAULT 1.0,
            tag          TEXT,
            status       TEXT    DEFAULT 'pending',
            reason       TEXT,
            created_at   TEXT    DEFAULT (datetime('now'))
        )
        """
    )


def run(**kwargs):
    max_correlation    = float(kwargs.get("max_correlation",    0.7))
    lookback_hours     = int(kwargs.get("lookback_hours",       48))
    min_bars           = int(kwargs.get("min_bars",             24))
    symbols_to_check   = kwargs.get("symbols_to_check",         None)
    strategy           = kwargs.get("strategy",                 "ema3")
    venue              = kwargs.get("venue",                    "paper")
    base_lot_size      = float(kwargs.get("base_lot_size",      1.0))
    resolution         = kwargs.get("resolution",               "15m")
    sl_pct             = float(kwargs.get("sl_pct",             2.0))
    tp_pct             = float(kwargs.get("tp_pct",             0.0))
    trail_pct          = float(kwargs.get("trail_pct",          1.0))
    trail_activate_pct = float(kwargs.get("trail_activate_pct", 1.0))

    now_str    = datetime.now(timezone.utc).isoformat() + "Z"
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=lookback_hours)

    client = DeltaClient(base_url=_BASE_URL)

    # ------------------------------------------------------------------
    # Step 1 — Resolve candidate symbols
    # ------------------------------------------------------------------
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        _ensure_pending_table(conn)

        if symbols_to_check:
            # Use symbols provided directly in params
            candidates = [
                {
                    "symbol":            s.strip(),
                    "strategy":          strategy,
                    "resolution":        resolution,
                    "venue":             venue,
                    "size":              base_lot_size,
                    "params_json":       "{}",
                    "sl_pct":            sl_pct,
                    "tp_pct":            tp_pct,
                    "trail_pct":         trail_pct,
                    "trail_activate_pct":trail_activate_pct,
                    "tag":               "anti_correlation_deployer",
                    "pending_id":        None,
                }
                for s in (
                    symbols_to_check
                    if isinstance(symbols_to_check, list)
                    else symbols_to_check.split(",")
                )
            ]
        else:
            # Read from pending_deployments table
            pending = conn.execute(
                "SELECT * FROM pending_deployments WHERE status='pending'"
            ).fetchall()
            candidates = [dict(r) for r in pending]
            for c in candidates:
                c["pending_id"] = c.pop("id", None)

        # Fetch all currently open positions
        open_rows = conn.execute(
            "SELECT DISTINCT symbol FROM deployments "
            "WHERE status='running' AND open_side IS NOT NULL"
        ).fetchall()

    open_symbols = [r["symbol"] for r in open_rows]

    if not candidates:
        return (
            "Anti-Correlation Deployer: No candidate symbols to evaluate. "
            "Add symbols to pending_deployments or set symbols_to_check "
            "in params_json."
        )

    # ------------------------------------------------------------------
    # Step 2 — Fetch returns for all open position symbols
    # ------------------------------------------------------------------
    open_returns: Dict[str, List[float]] = {}

    for sym in open_symbols:
        rets = _fetch_returns(client, sym, start_time, end_time, min_bars)
        if rets:
            open_returns[sym] = rets

    messages  = []
    deployed  = 0
    rejected  = 0
    errors    = []

    # ------------------------------------------------------------------
    # Step 3 — Evaluate each candidate
    # ------------------------------------------------------------------
    for candidate in candidates:
        sym        = candidate["symbol"]
        cand_strat = candidate.get("strategy",   strategy)
        cand_venue = candidate.get("venue",      venue)
        cand_res   = candidate.get("resolution", resolution)
        cand_size  = float(candidate.get("size", base_lot_size))
        cand_sl    = float(candidate.get("sl_pct",            sl_pct))
        cand_tp    = float(candidate.get("tp_pct",            tp_pct))
        cand_trail = float(candidate.get("trail_pct",         trail_pct))
        cand_tact  = float(candidate.get("trail_activate_pct",trail_activate_pct))
        cand_tag   = candidate.get("tag", "anti_correlation_deployer")
        pending_id = candidate.get("pending_id")

        # Fetch candidate returns
        cand_rets = _fetch_returns(
            client, sym, start_time, end_time, min_bars
        )
        if cand_rets is None:
            errors.append(
                f"WARN | {sym}: insufficient bar data — skipping"
            )
            continue

        # Calculate max correlation with open positions
        max_corr      = 0.0
        max_corr_sym  = None

        if not open_returns:
            # No open positions — no correlation risk
            max_corr     = 0.0
            max_corr_sym = None
        else:
            for open_sym, open_rets in open_returns.items():
                if open_sym == sym:
                    # Same symbol already open — skip
                    max_corr     = 1.0
                    max_corr_sym = open_sym
                    break
                corr = abs(_pearson(cand_rets, open_rets))
                if corr > max_corr:
                    max_corr     = corr
                    max_corr_sym = open_sym

        passes = max_corr < max_correlation

        if passes:
            # Deploy the bot
            try:
                with connect() as conn:
                    # Check not already running
                    existing = conn.execute(
                        "SELECT id FROM deployments "
                        "WHERE symbol=? AND strategy=? AND status='running'",
                        (sym, cand_strat),
                    ).fetchone()

                    if existing:
                        messages.append(
                            f"SKIP | {sym}: {cand_strat} already running"
                        )
                        if pending_id:
                            conn.execute(
                                "UPDATE pending_deployments "
                                "SET status='skipped', reason=? WHERE id=?",
                                ("already running", pending_id),
                            )
                        continue

                    now_iso = datetime.now(timezone.utc).isoformat()
                    name    = f"ACD {cand_strat.upper()} {sym}"
                    i_live  = 1 if cand_venue == "live" else 0

                    info = conn.execute(
                        """INSERT INTO deployments(
                            name, venue, strategy, symbol, resolution,
                            size, params_json,
                            sl_pct, tp_pct, trail_pct,
                            trail_activate_pct, breakeven_after_pct,
                            reduce_only, interval_sec, status,
                            i_understand_live, leverage, sync_leverage,
                            force_entry, created_at, started_at, tag
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',
                                  ?,?,?,?,?,?,?)""",
                        (
                            name, cand_venue, cand_strat, sym, cand_res,
                            max(1, round(cand_size)), "{}",
                            cand_sl, cand_tp, cand_trail,
                            cand_tact, 0.0,
                            0, 300, i_live, 1, 1, 0,
                            now_iso, now_iso, cand_tag,
                        ),
                    )
                    dep_id = info.lastrowid

                    conn.execute(
                        "INSERT INTO deployment_events"
                        "(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'anti_correlation_deployer', ?)",
                        (
                            dep_id, now_str,
                            f"Deployed — max correlation with open positions "
                            f"{max_corr:.3f} < threshold {max_correlation:.2f}"
                            + (
                                f" (most correlated: {max_corr_sym})"
                                if max_corr_sym else " (no open positions)"
                            ),
                        ),
                    )

                    if pending_id:
                        with connect() as c:
                            c.execute(
                                "UPDATE pending_deployments "
                                "SET status='deployed', reason=? WHERE id=?",
                                (
                                    f"corr={max_corr:.3f} < {max_correlation:.2f}",
                                    pending_id,
                                ),
                            )

                deployed += 1
                corr_str = (
                    f"max_corr={max_corr:.3f} with {max_corr_sym}"
                    if max_corr_sym
                    else "no open positions"
                )
                messages.append(
                    f"DEPLOYED | {sym} ({cand_strat} {cand_res}): "
                    f"Bot #{dep_id} — {corr_str}"
                )

                # Add to open_returns so subsequent candidates
                # are checked against this newly deployed symbol too
                open_returns[sym] = cand_rets

            except Exception as e:
                err = f"ERR | {sym}: deploy failed — {e}"
                errors.append(err)
                messages.append(err)

        else:
            # Reject — too correlated
            rejected += 1
            reason = (
                f"correlation {max_corr:.3f} with {max_corr_sym} "
                f">= threshold {max_correlation:.2f}"
            )
            messages.append(
                f"REJECTED | {sym} ({cand_strat}): {reason}"
            )

            try:
                if pending_id:
                    with connect() as conn:
                        conn.execute(
                            "UPDATE pending_deployments "
                            "SET status='rejected', reason=? WHERE id=?",
                            (reason, pending_id),
                        )
            except Exception as e:
                errors.append(
                    f"ERR | {sym}: pending update failed — {e}"
                )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    summary = (
        f"Anti-Correlation Deployer complete — "
        f"candidates={len(candidates)}, "
        f"deployed={deployed}, "
        f"rejected={rejected}, "
        f"open_positions_checked={len(open_symbols)}"
    )
    messages.insert(0, summary)

    if errors:
        messages.append("Errors:")
        messages.extend(f"  {e}" for e in errors)

    return "### Anti-Correlation Deployer\n\n" + "\n".join(messages)

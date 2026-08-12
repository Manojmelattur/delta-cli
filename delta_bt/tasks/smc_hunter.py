"""SMC Hunter Task.

Scans the top N perpetual futures symbols by USD turnover using SMC
strategies, applies a 30-day profitability filter, and optionally
auto-deploys bots for detected setups.

Kwargs:
    venue                (str,   default "paper")  — Deployment venue.
    auto_deploy          (bool,  default False)    — Deploy bots for found setups.
    dry_run              (bool,  default False)    — Log without deploying.
    base_lot_size        (int,   default 1)        — Lot size for auto-deployed bots.
    top_n_symbols        (int,   default 15)       — Number of top symbols to scan.
    lookback_days        (int,   default 7)        — Signal detection window.
    profit_lookback_days (int,   default 30)       — Profitability check window.
    min_win_rate         (float, default 0.50)     — Minimum win rate threshold.
    workers              (int,   default 8)        — Parallel scan workers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.scanner.days_scanner import scan_strategy_setups, ScannerSetup
from delta_bt.store.db import connect

_SMC_STRATEGIES = ["smc_ob", "smc_ob_fvg", "smc_liquidity_sweep", "smc_bos_retest"]


def _to_bool(val, default: bool = False) -> bool:
    """Safe bool cast — handles True/False and "true"/"false" strings."""
    if isinstance(val, bool):
        return val
    return str(val).lower() == "true"


def run(**kwargs) -> str:
    """SMC Hunter Task."""

    # --- Parse kwargs ---
    venue                = str(kwargs.get("venue",                "paper"))
    top_n                = int(kwargs.get("top_n_symbols",        15))
    lookback_days        = int(kwargs.get("lookback_days",        7))
    profit_lookback_days = int(kwargs.get("profit_lookback_days", 30))
    min_win_rate         = float(kwargs.get("min_win_rate",       0.40))
    workers              = int(kwargs.get("workers",              8))
    base_size            = max(1, int(kwargs.get("base_lot_size", 1)))
    auto_deploy          = _to_bool(kwargs.get("auto_deploy",     False))
    dry_run              = _to_bool(kwargs.get("dry_run",         False))

    user_symbols_raw     = kwargs.get("coins", kwargs.get("symbols", kwargs.get("symbol_list", [])))
    user_symbols: List[str] = []
    if isinstance(user_symbols_raw, str):
        user_symbols = [s.strip() for s in user_symbols_raw.split(",") if s.strip()]
    elif isinstance(user_symbols_raw, list):
        user_symbols = [str(s).strip() for s in user_symbols_raw if str(s).strip()]

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    client = DeltaClient(base_url="https://api.india.delta.exchange")
    symbols: List[str] = []

    if user_symbols:
        symbols = user_symbols
    else:
        # --- Fetch all symbols ---
        try:
            tickers = client.tickers(contract_types="perpetual_futures")
            symbols = [t["symbol"] for t in tickers if "symbol" in t]
        except Exception as e:
            return (
                f"### SMC Hunter\n\n"
                f"Date: {now_str}\n\n"
                f"ERR | Failed to fetch tickers: {e}"
            )

    if not symbols:
        return (
            f"### SMC Hunter\n\n"
            f"Date: {now_str}\n\n"
            f"WARN | No symbols returned from ticker feed."
        )

    # --- Run scanner ---
    try:
        setups: List[ScannerSetup] = scan_strategy_setups(
            client=client,
            symbols=symbols,
            resolutions=["15m", "1h"],
            strategies=_SMC_STRATEGIES,
            workers=workers,
            lookback_days=lookback_days,
            profit_lookback_days=profit_lookback_days,
            min_win_rate=min_win_rate,
        )
    except Exception as e:
        return (
            f"### SMC Hunter\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Scanner failed: {e}"
        )

    if not setups:
        return (
            f"### SMC Hunter\n\n"
            f"Date: {now_str}\n\n"
            f"Scanned {len(symbols)} symbols across 2 resolutions "
            f"using {len(_SMC_STRATEGIES)} SMC strategies. "
            f"No setups found."
        )

    messages = [
        f"### SMC Hunter\n\n"
        f"Date       : {now_str}\n"
        f"Symbols    : {len(symbols)}\n"
        f"Setups     : {len(setups)}\n"
        f"Auto-deploy: {'yes' if auto_deploy else 'no'}"
        f"{' (dry run)' if dry_run else ''}\n"
    ]

    for s in setups:
        # s.signal is already a plain str ("BUY" / "SELL" / "LONG" / "SHORT")
        messages.append(
            f"Found {s.signal} setup on {s.symbol} "
            f"using {s.strategy} ({s.resolution}) @ {s.price:.4f} "
            f"| 30d PnL={s.total_pnl:.2f} "
            f"WR={s.win_rate:.0%} "
            f"Trades={s.trade_count}"
        )

        if not auto_deploy:
            continue

        # Exposure gate: block new entries while gross exposure >= limit
        from delta_bt.tasks.exposure_gate import exposure_blocked
        _blocked, _reason = exposure_blocked()
        if _blocked:
            messages.append(f"> Entry blocked ({s.symbol}): {_reason}")
            continue

        # --- Auto-deploy ---
        try:
            with connect() as conn:
                existing = conn.execute(
                    """
                    SELECT id FROM deployments
                    WHERE symbol   = ?
                      AND strategy = ?
                      AND status   = 'running'
                    """,
                    (s.symbol, s.strategy),
                ).fetchone()

                if existing:
                    messages.append(
                        f"> Skipped: {s.strategy} already running "
                        f"on {s.symbol}."
                    )
                    continue

                name = f"smc_{s.strategy.replace('smc_', '')}_{s.symbol}_{s.resolution}"
                now  = datetime.now(timezone.utc).isoformat() + "Z"

                if dry_run:
                    messages.append(
                        f"> DRY | Would deploy: {name} "
                        f"(venue={venue} size={base_size} "
                        f"sl=2% tsl=1% trail_activate=1%)"
                    )
                    continue

                info = conn.execute(
                    """
                    INSERT INTO deployments(
                        name, venue, strategy, symbol, resolution,
                        size, params_json,
                        sl_pct, tp_pct, trail_pct,
                        trail_activate_pct, breakeven_after_pct,
                        reduce_only, interval_sec, status,
                        i_understand_live, leverage,
                        sync_leverage, force_entry,
                        created_at, started_at, tag
                    ) VALUES (
                        ?,?,?,?,?,
                        ?,?,
                        ?,?,?,
                        ?,?,
                        ?,?,'running',
                        ?,?,
                        ?,?,
                        ?,?,?
                    )
                    """,
                    (
                        name, venue, s.strategy, s.symbol, s.resolution,
                        base_size, "{}",
                        2.0, 0.0, 1.0,
                        # trail_activate_pct=1.0: trail only kicks in after
                        # 1% profit — prevents immediate trail-stop on entry.
                        1.0, 0.0,
                        0, 300,
                        # i_understand_live respects venue.
                        1 if venue == "live" else 0,
                        1,
                        1, 0,
                        now, now, "smc_hunter",
                    ),
                )
                dep_id = info.lastrowid

                conn.execute(
                    "INSERT INTO deployment_events"
                    "(deployment_id, ts, kind, message) "
                    "VALUES (?, ?, 'start', ?)",
                    (dep_id, now, "auto-deployed by SMC Hunter"),
                )
                conn.commit()

                messages.append(
                    f"> Deployed Bot #{dep_id} — "
                    f"venue={venue} size={base_size} "
                    f"sl=2% tsl=1% (activates at +1%)"
                )

        except Exception as e:
            messages.append(
                f"> ERR | Failed to deploy {s.symbol} "
                f"{s.strategy}: {e}"
            )

    return "\n\n".join(messages)

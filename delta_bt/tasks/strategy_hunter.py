
# # Fix 1a: corrected import path (removed invalid "python." prefix)
# # Fix 1b: corrected misspelled function name "startey_scanner" -> "scan_strategy_setups"
# from delta_bt.scanner.days_scanner import scan_strategy_setups

# import json
# from datetime import datetime, timezone

# # Fix 2: corrected base URL to the proper Delta Exchange India production endpoint
# from delta_bt.data.delta_client import DeltaClient
# from delta_bt.store.db import connect


# def run(**kwargs):
#     client = DeltaClient(base_url="https://api.india.delta.exchange")
#     auto_deploy = kwargs.get("auto_deploy", False)
#     venue = kwargs.get("venue", "paper")
#     strategy=kwargs.get("strategy", "ema3")
#     # Get top 15 symbols by USD turnover
#     tickers = client.tickers(contract_types="perpetual_futures")
#     tickers.sort(key=lambda x: float(x.get("turnover_usd") or x.get("turnover") or 0), reverse=True)
#     symbols = [t["symbol"] for t in tickers[:15] if "symbol" in t]

#     # Fix 1b: use the correctly named function
#     setups = scan_strategy_setups(
#         client=client,
#         symbols=symbols,
#         resolutions=["15m", "30m", "1h"],
#         strategies=[strategy],
#         workers=8,
#         lookback_days=7
#     )

#     if not setups:
#         return f"Scanned {len(symbols)} symbols. No strategy_hunter setups found."

#     messages = []

#     for s in setups:
#         messages.append(
#             f"Found {s.signal} setup on {s.symbol} using {s.strategy} ({s.resolution}) @ {s.price}"
#         )

#         if auto_deploy:
#             with connect() as conn:
#                 existing = conn.execute(
#                     "SELECT id FROM deployments WHERE symbol=? AND strategy=? AND status='running'",
#                     (s.symbol, s.strategy),
#                 ).fetchone()

#                 if existing:
#                     messages.append(
#                         f"> Skipped auto-deploy: {s.strategy} already running on {s.symbol}."
#                     )
#                     continue

#                 now = datetime.now(timezone.utc).isoformat()
#                 name = (
#                     f"strategy_hunter_{s.strategy.replace('strategy_hunter_', '').upper()} {s.symbol}"
#                 )

#                 size = float(kwargs.get("base_lot_size", 1.0))

#                 info = conn.execute(
#                     """INSERT INTO deployments(
#                         name, venue, strategy, symbol, resolution, size, params_json,
#                         sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
#                         reduce_only, interval_sec, status, i_understand_live, leverage,
#                         sync_leverage, force_entry, created_at, started_at, tag
#                     ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
#                     (
#                         name, venue, s.strategy, s.symbol, s.resolution, size, "{}",
#                         2.0, 0.0, 1.0, 0.0, 0.0,
#                         0, 300, 0, 1, 1, 0,
#                         now, now, "strategy_hunter",
#                     ),
#                 )
#                 dep_id = info.lastrowid

#                 conn.execute(
#                     "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
#                     "VALUES (?, ?, 'start', ?)",
#                     (dep_id, now, "auto-deployed by strategy_hunter"),
#                 )

#                 messages.append(
#                     f"> Auto-Deployed Bot #{dep_id}. Venue: {venue}, SL: 2%, TSL: 1%."
#                 )

#     return "### strategy_hunter Results\n\n" + "\n\n".join(messages)
"""Strategy Hunter / Scanner Task.

Scans the top N perpetual futures symbols by USD turnover, runs
strategy setup detection across multiple resolutions, and optionally
auto-deploys bots for detected setups.

Kwargs:
    strategy        (str,   default "ema3")    — Strategy name to scan.
    venue           (str,   default "paper")   — Deployment venue.
    auto_deploy     (bool,  default False)     — Deploy bots for found setups.
    dry_run         (bool,  default False)     — Log without deploying.
    base_lot_size   (int,   default 1)         — Lot size for auto-deployed bots.
    top_n_symbols   (int,   default 15)        — Number of top symbols to scan.
    resolutions     (list,  default [...])     — Resolutions to scan.
    lookback_days   (int,   default 7)         — Bar history for scanner.
    workers         (int,   default 8)         — Parallel scan workers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.scanner.days_scanner import scan_strategy_setups, ScannerSetup
from delta_bt.store.db import connect

# Known valid strategy names — used to validate the `strategy` kwarg.
_KNOWN_STRATEGIES = {
    "ema3", "macd", "macd_divergence", "rsi_mr", "rsi_divergence",
    "fvg", "grid", "momentum_breakout", "donchian_breakout",
    "atr_channel_breakout", "obv_trend", "stochastic_rsi",
    "cci_reversion", "bb_ha_supertrend", "supertrend_mom",
    "supertrend_mom_v2", "keltner_squeeze", "vwap", "vwap_bands",
    "smc_bos_retest", "smc_choch_bos", "smc_liquidity_sweep",
    "smc_ob", "smc_ob_fvg", "inside_bar_breakout",
    "three_bar_reversal", "price_action_engulfing",
    "price_action_pinbar", "ichimoku_cloud",
    "options_iron_condor", "move_volatility_straddle",
}


def _to_bool(val, default: bool = False) -> bool:
    """Safe bool cast — handles True/False and "true"/"false" strings."""
    if isinstance(val, bool):
        return val
    return str(val).lower() == "true"


def run(**kwargs) -> str:
    """Strategy Hunter / Scanner Task."""

    # --- Parse kwargs ---
    strategy    = str(kwargs.get("strategy",      "ema3"))
    venue       = str(kwargs.get("venue",         "paper"))
    top_n       = int(kwargs.get("top_n_symbols", 15))
    lookback    = int(kwargs.get("lookback_days", 7))
    workers     = int(kwargs.get("workers",       8))
    base_size   = max(1, int(kwargs.get("base_lot_size", 1)))
    resolutions = kwargs.get("resolutions", ["15m", "30m", "1h"])
    auto_deploy = _to_bool(kwargs.get("auto_deploy", False))
    dry_run     = _to_bool(kwargs.get("dry_run",     False))

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Validate strategy ---
    if strategy not in _KNOWN_STRATEGIES:
        return (
            f"### Strategy Hunter\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Unknown strategy '{strategy}'. "
            f"Valid strategies: {', '.join(sorted(_KNOWN_STRATEGIES))}"
        )

    # --- Fetch symbols ---
    client = DeltaClient(base_url="https://api.india.delta.exchange")
    
    user_symbols_raw = kwargs.get("coins", kwargs.get("symbols", []))
    if isinstance(user_symbols_raw, str):
        user_symbols = [s.strip() for s in user_symbols_raw.split(",") if s.strip()]
    elif isinstance(user_symbols_raw, list):
        user_symbols = [str(s).strip() for s in user_symbols_raw if str(s).strip()]
    else:
        user_symbols = []

    if user_symbols:
        symbols = user_symbols
    else:
        try:
            tickers = client.tickers(contract_types="perpetual_futures")
            # Return all coins if not specified
            symbols = [t["symbol"] for t in tickers if "symbol" in t]
        except Exception as e:
            return (
                f"### Strategy Hunter\n\n"
                f"Date: {now_str}\n\n"
                f"ERR | Failed to fetch tickers: {e}"
            )

    if not symbols:
        return (
            f"### Strategy Hunter\n\n"
            f"Date: {now_str}\n\n"
            f"WARN | No symbols returned from ticker feed."
        )

    # --- Run scanner ---
    try:
        setups: List[ScannerSetup] = scan_strategy_setups(
            client=client,
            symbols=symbols,
            resolutions=resolutions,
            strategies=[strategy],
            workers=workers,
            lookback_days=lookback,
        )
    except Exception as e:
        return (
            f"### Strategy Hunter\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Scanner failed: {e}"
        )

    if not setups:
        return (
            f"### Strategy Hunter\n\n"
            f"Date: {now_str}\n\n"
            f"Scanned {len(symbols)} symbols across "
            f"{len(resolutions)} resolutions "
            f"using strategy '{strategy}'. "
            f"No setups found."
        )

    messages = [
        f"### Strategy Hunter\n\n"
        f"Date       : {now_str}\n"
        f"Strategy   : {strategy}\n"
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
            f"| PnL={s.total_pnl:.2f} "
            f"WR={s.win_rate:.0%} "
            f"trades={s.trade_count}"
        )

        if not auto_deploy:
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

                name = f"scanner_{s.strategy}_{s.symbol}_{s.resolution}"
                now  = datetime.now(timezone.utc).isoformat() + "Z"

                if dry_run:
                    messages.append(
                        f"> DRY | Would deploy: {name} "
                        f"(venue={venue} size={base_size} "
                        f"sl=2% tsl=1%)"
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
                        0.0, 0.0,
                        0, 300,
                        0, 1,
                        1, 0,
                        now, now, "strategy_hunter",
                    ),
                )
                dep_id = info.lastrowid

                conn.execute(
                    "INSERT INTO deployment_events"
                    "(deployment_id, ts, kind, message) "
                    "VALUES (?, ?, 'start', ?)",
                    (dep_id, now, "auto-deployed by strategy_hunter"),
                )
                conn.commit()

                messages.append(
                    f"> Deployed Bot #{dep_id} — "
                    f"venue={venue} size={base_size} "
                    f"sl=2% tsl=1%"
                )

        except Exception as e:
            messages.append(
                f"> ERR | Failed to deploy {s.symbol} "
                f"{s.strategy}: {e}"
            )

    return "\n\n".join(messages)

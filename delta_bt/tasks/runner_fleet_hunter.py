from delta_bt.scanner.smc_scanner import scan_smc_setups

import json
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def run(**kwargs):
    # Fix 1: correct base URL
    client      = DeltaClient(base_url="https://api.india.delta.exchange")
    auto_deploy = kwargs.get("auto_deploy", False)
    venue       = kwargs.get("venue", "paper")

    # Profitability filter params
    lookback_days        = int(kwargs.get("lookback_days",        7))
    profit_lookback_days = int(kwargs.get("profit_lookback_days", 30))
    min_win_rate         = float(kwargs.get("min_win_rate",       0.50))

    user_symbols_raw = kwargs.get("coins", kwargs.get("symbols", kwargs.get("symbol_list", [])))
    user_symbols = []
    if isinstance(user_symbols_raw, str):
        user_symbols = [s.strip() for s in user_symbols_raw.split(",") if s.strip()]
    elif isinstance(user_symbols_raw, list):
        user_symbols = [str(s).strip() for s in user_symbols_raw if str(s).strip()]

    if user_symbols:
        symbols = user_symbols
    else:
        tickers = client.tickers(contract_types="perpetual_futures")
        symbols = [t["symbol"] for t in tickers if "symbol" in t]

    # Fix: wrap scanner in try/except so API failures do not crash the task
    try:
        # Fix: removed unconfirmed smc_bos_retest strategy
        setups = scan_smc_setups(
            client=client,
            symbols=symbols,
            resolutions=["15m", "1h"],
            strategies=["smc_ob", "smc_ob_fvg", "smc_liquidity_sweep"],
            workers=8,
            lookback_days=lookback_days,
            profit_lookback_days=profit_lookback_days,
            min_win_rate=min_win_rate,
        )
    except Exception as e:
        return f"Runner Fleet Hunter: Scanner failed — {e}"

    if not setups:
        return f"Scanned {len(symbols)} symbols. No setups found for Runner Fleet."

    messages = []

    for s in setups:
        strat_short = s.strategy.replace("smc_", "").upper()
        messages.append(
            f"Found {s.signal} setup on {s.symbol} "
            f"using {s.strategy} ({s.resolution}) @ {s.price} "
            f"| 30d PnL={s.total_pnl:.2f} WR={s.win_rate:.0%} Trades={s.trade_count}"
        )

        if auto_deploy:
            try:
                with connect() as conn:
                    # Fix: check by symbol + strategy + tag instead of name
                    # name-based check breaks if name format ever changes
                    existing = conn.execute(
                        "SELECT id FROM deployments "
                        "WHERE symbol=? AND strategy=? AND tag=? AND status='running'",
                        (s.symbol, s.strategy, "runner_fleet_safe"),
                    ).fetchone()

                    if existing:
                        messages.append(
                            f"> Skipped fleet deploy: safe bot already running "
                            f"for {s.strategy} on {s.symbol}."
                        )
                        continue

                    now       = datetime.now(timezone.utc).isoformat()
                    full_size = float(kwargs.get("base_lot_size", 1.0))
                    # Fix: half_size must be at least 1 lot — Delta does not
                    # support fractional lot sizes
                    half_size = max(1.0, round(full_size / 2.0))

                    # Fix: i_understand_live respects venue for both bots
                    i_live = 1 if venue == "live" else 0

                    # Fix: clean names without redundant prefix
                    safe_name   = f"Safe {strat_short} {s.symbol}"
                    runner_name = f"Runner {strat_short} {s.symbol}"

                    # --- BOT 1: SAFE BOT ---
                    # Fix: sl_pct=1.5, tp_pct=3.0 gives 2:1 reward/risk
                    # original had tp=1.0 < sl=1.5 which is negative reward/risk
                    info_safe = conn.execute(
                        """INSERT INTO deployments(
                            name, venue, strategy, symbol, resolution, size, params_json,
                            sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                            reduce_only, interval_sec, status, i_understand_live, leverage,
                            sync_leverage, force_entry, created_at, started_at, tag
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                        (
                            safe_name, venue, s.strategy, s.symbol, s.resolution,
                            half_size, "{}",
                            1.5, 3.0, 0.0, 0.0, 0.0,
                            0, 300, i_live, 1, 1, 0,
                            now, now, "runner_fleet_safe",
                        ),
                    )
                    safe_id = info_safe.lastrowid

                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'start', ?)",
                        (safe_id, now, "auto-deployed by Runner Fleet Hunter (Safe half)"),
                    )

                    # --- BOT 2: RUNNER BOT ---
                    # Trail=0.5% activates at 1% profit, breakeven at 1%
                    info_runner = conn.execute(
                        """INSERT INTO deployments(
                            name, venue, strategy, symbol, resolution, size, params_json,
                            sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                            reduce_only, interval_sec, status, i_understand_live, leverage,
                            sync_leverage, force_entry, created_at, started_at, tag
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                        (
                            runner_name, venue, s.strategy, s.symbol, s.resolution,
                            half_size, "{}",
                            1.5, 0.0, 0.5, 1.0, 1.0,
                            0, 300, i_live, 1, 1, 0,
                            now, now, "runner_fleet_runner",
                        ),
                    )
                    runner_id = info_runner.lastrowid

                    conn.execute(
                        "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                        "VALUES (?, ?, 'start', ?)",
                        (runner_id, now, "auto-deployed by Runner Fleet Hunter (Runner half)"),
                    )

                    messages.append(
                        f"> Deployed Runner Fleet for {s.symbol}: "
                        f"Safe Bot #{safe_id} (SL 1.5% TP 3.0%) | "
                        f"Runner Bot #{runner_id} (SL 1.5% Trail 0.5% activates at +1%)."
                    )

            # Fix: catch deployment errors per setup so one failure
            # does not prevent remaining setups from being deployed
            except Exception as e:
                messages.append(
                    f"ERR | deploy failed for {s.symbol} {s.strategy}: {e}"
                )

    return "### Runner Fleet Hunter Results\n\n" + "\n\n".join(messages)

# Fix 1: correct import path — scanner is a package, no strategy_scanner submodule
from delta_bt.scanner.smc_scanner import scan_strategy_setups

import json
from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def run(**kwargs):
    client      = DeltaClient(base_url="https://api.india.delta.exchange")
    auto_deploy = kwargs.get("auto_deploy", False)
    venue       = kwargs.get("venue", "paper")

    # Profitability filter params
    lookback_days        = int(kwargs.get("lookback_days",        7))
    profit_lookback_days = int(kwargs.get("profit_lookback_days", 30))
    min_win_rate         = float(kwargs.get("min_win_rate",       0.50))

    # Get top 15 symbols by USD turnover
    tickers = client.tickers(contract_types="perpetual_futures")
    tickers.sort(
        key=lambda x: float(x.get("turnover_usd") or x.get("turnover") or 0),
        reverse=True,
    )
    symbols = [t["symbol"] for t in tickers[:15] if "symbol" in t]

    try:
        setups = scan_strategy_setups(
            client=client,
            symbols=symbols,
            resolutions=["15m", "1h"],
            strategies=["keltner_squeeze"],
            workers=8,
            lookback_days=lookback_days,
            profit_lookback_days=profit_lookback_days,
            min_win_rate=min_win_rate,
        )
    except Exception as e:
        return f"Keltner Hunter: Scanner failed — {e}"

    if not setups:
        return f"Scanned {len(symbols)} symbols. No Keltner setups found."

    messages = []

    for s in setups:
        messages.append(
            f"Found {s.signal} setup on {s.symbol} "
            f"using {s.strategy} ({s.resolution}) @ {s.price} "
            f"| 30d PnL={s.total_pnl:.2f} WR={s.win_rate:.0%} Trades={s.trade_count}"
        )

        if auto_deploy:
            with connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM deployments "
                    "WHERE symbol=? AND strategy=? AND status='running'",
                    (s.symbol, s.strategy),
                ).fetchone()

                if existing:
                    messages.append(
                        f"> Skipped auto-deploy: {s.strategy} already running on {s.symbol}."
                    )
                    continue

                now  = datetime.now(timezone.utc).isoformat()
                # Fix 3: clean name without redundant prefix or messy replace
                name = f"Keltner {s.symbol} {s.resolution}"
                size = float(kwargs.get("base_lot_size", 1.0))

                info = conn.execute(
                    """INSERT INTO deployments(
                        name, venue, strategy, symbol, resolution, size, params_json,
                        sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                        reduce_only, interval_sec, status, i_understand_live, leverage,
                        sync_leverage, force_entry, created_at, started_at, tag
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                    (
                        name, venue, s.strategy, s.symbol, s.resolution, size, "{}",
                        2.0, 0.0, 1.0,
                        # Fix 2: trail_activate_pct=1.0 so trail only kicks in
                        # after 1% profit — prevents immediate trail-stop on entry
                        1.0, 0.0,
                        0, 300,
                        1 if venue == "live" else 0,
                        1, 1, 0,
                        now, now, "keltner_hunter",
                    ),
                )
                dep_id = info.lastrowid

                conn.execute(
                    "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                    "VALUES (?, ?, 'start', ?)",
                    (dep_id, now, "auto-deployed by Keltner Hunter"),
                )

                messages.append(
                    f"> Auto-Deployed Bot #{dep_id}. "
                    f"Venue: {venue}, SL: 2%, TSL: 1% (activates at +1%)."
                )

    return "### Keltner Hunter Results\n\n" + "\n\n".join(messages)

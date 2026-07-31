import json
import statistics
from datetime import datetime, timezone, timedelta

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


def run(**kwargs):
    # Fix 1: correct base URL
    client      = DeltaClient(base_url="https://api.india.delta.exchange")
    auto_deploy = kwargs.get("auto_deploy", False)
    venue       = kwargs.get("venue", "paper")

    # Pairs to monitor — configurable via kwargs
    # Fix 8: removed ADAUSD/DOTUSD which may not exist on Delta Exchange India
    default_pairs = [
        ("BTCUSD", "ETHUSD"),
        ("SOLUSD", "AVAXUSD"),
    ]
    pairs = kwargs.get("pairs", default_pairs)

    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=3)  # 72 hours of 1h candles

    messages = []
    signals  = 0   # Fix 3: renamed from actions — counts divergences found
    deployed = 0   # Fix 3: separate counter for actual deployments

    for sym_a, sym_b in pairs:
        try:
            candles_a = client.candles(sym_a, "1h", start, end)
            candles_b = client.candles(sym_b, "1h", start, end)

            if not candles_a or not candles_b:
                continue

            # Fix 2: align by timestamp instead of requiring equal length.
            # Missing bars on one side will not discard the entire pair.
            times_a = {k["time"]: float(k["close"]) for k in candles_a}
            times_b = {k["time"]: float(k["close"]) for k in candles_b}
            common  = sorted(set(times_a) & set(times_b))
            ratios  = [
                times_a[t] / times_b[t]
                for t in common
                if times_b[t] > 0
            ]

            if len(ratios) < 24:
                continue

            current_ratio = ratios[-1]
            mean_ratio    = statistics.mean(ratios)
            std_ratio     = statistics.stdev(ratios)

            if std_ratio == 0:
                continue

            z_score = (current_ratio - mean_ratio) / std_ratio

            if abs(z_score) > 2.5:
                signals += 1
                # Z < -2.5: sym_a undervalued relative to sym_b → buy sym_a
                # Z > +2.5: sym_b undervalued relative to sym_a → buy sym_b
                target_symbol = sym_a if z_score < -2.5 else sym_b
                strategy_name = "vwap_reversion"

                messages.append(
                    f"Stat Arb Alert: {sym_a} vs {sym_b} divergence! "
                    f"Z-Score: {z_score:.2f} "
                    f"(Ratio: {current_ratio:.4f}, Mean: {mean_ratio:.4f}) "
                    f"-> Target: {target_symbol}"
                )

                if auto_deploy:
                    with connect() as conn:
                        existing = conn.execute(
                            "SELECT id FROM deployments "
                            "WHERE symbol=? AND strategy=? AND status='running'",
                            (target_symbol, strategy_name),
                        ).fetchone()

                        if existing:
                            messages.append(
                                f"> Skipped auto-deploy: {strategy_name} "
                                f"already running on {target_symbol}."
                            )
                            continue

                        now  = datetime.now(timezone.utc).isoformat()
                        # Fix 4: removed redundant "stat_arb_scanner_" prefix
                        name = f"StatArb {target_symbol}"
                        size = float(kwargs.get("base_lot_size", 1.0))

                        # Fix 6: removed irrelevant adx_len param from vwap_reversion
                        info = conn.execute(
                            """INSERT INTO deployments(
                                name, venue, strategy, symbol, resolution, size, params_json,
                                sl_pct, tp_pct, trail_pct, trail_activate_pct, breakeven_after_pct,
                                reduce_only, interval_sec, status, i_understand_live, leverage,
                                sync_leverage, force_entry, created_at, started_at, tag
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'running',?,?,?,?,?,?,?)""",
                            (
                                name, venue, strategy_name,
                                target_symbol, "15m", size, "{}",
                                3.0, 5.0, 1.5, 2.0, 1.0,
                                0, 300,
                                # Fix 5: i_understand_live respects venue
                                1 if venue == "live" else 0,
                                1, 1, 0,
                                now, now, "stat_arb_scanner",
                            ),
                        )
                        dep_id = info.lastrowid

                        conn.execute(
                            "INSERT INTO deployment_events(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'start', ?)",
                            (dep_id, now, "auto-deployed by Stat Arb Scanner"),
                        )
                        deployed += 1
                        messages.append(
                            f"> Deployed Stat Arb Bot #{dep_id} on {target_symbol}. "
                            f"Venue: {venue}, SL: 3%, TP: 5%, TSL: 1.5%."
                        )
                else:
                    messages.append(
                        f"> Auto-deploy is OFF. Target asset: {target_symbol}"
                    )

        except Exception as e:
            messages.append(f"ERR | {sym_a}/{sym_b}: {e}")

    # Fix 3: use signals counter for "nothing found" check
    if signals == 0:
        return "Scanned statistical pairs. No major divergences (|Z| > 2.5) found."

    return "### Statistical Arbitrage Scanner\n\n" + "\n\n".join(messages)

"""Open Interest Spike Detector Task

Monitors OI changes across top perpetual symbols on Delta Exchange.
Large OI spikes often precede liquidation cascades or breakout moves.

Interpretation:
  OI spike + price rising  = new longs entering = bullish momentum
                             (but also builds up long liquidation risk)
  OI spike + price falling = new shorts entering = bearish momentum
                             (but also builds up short liquidation risk)
  OI spike + price flat    = positioning for a move = watch closely
  OI drop  + price moving  = liquidations occurring = volatile, be careful

Actions:
  - Logs findings to deployment_events on affected bots
  - If auto_pause=True, pauses bots on symbols with extreme OI spikes
  - Writes OI spike data to app_settings for other tasks

Params (set in task params_json):
    spike_threshold_pct  : OI change % to flag as a spike (default 10.0)
    extreme_threshold_pct: OI change % to trigger auto-pause (default 25.0)
    lookback_hours       : Hours to measure OI change over (default 1)
    auto_pause           : If True, pauses bots on spiking symbols (default False)
    top_n                : Number of top symbols to scan (default 20)
    resume_normal        : If True, resumes paused bots when OI normalises (default True)
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from delta_bt.data.delta_client import DeltaClient
from delta_bt.store.db import connect


_BASE_URL       = "https://api.india.delta.exchange"
_OI_SPIKE_KEY   = "market.oi_spikes"


def _pct_change(old: float, new: float) -> float:
    """Calculate percentage change from old to new value."""
    if old == 0:
        return 0.0
    return (new - old) / abs(old) * 100.0


def _oi_signal(oi_change_pct: float, price_change_pct: float) -> str:
    """Classify OI spike signal based on OI and price direction."""
    oi_up    = oi_change_pct > 0
    price_up = price_change_pct > 0

    if oi_up and price_up:
        return "LONG_BUILDUP"
    if oi_up and not price_up:
        return "SHORT_BUILDUP"
    if not oi_up and price_up:
        return "SHORT_SQUEEZE"
    return "LONG_LIQUIDATION"


def _signal_description(signal: str) -> str:
    return {
        "LONG_BUILDUP":      "New longs entering — bullish momentum, long liquidation risk building",
        "SHORT_BUILDUP":     "New shorts entering — bearish momentum, short squeeze risk building",
        "SHORT_SQUEEZE":     "Shorts being liquidated — price rising as OI drops",
        "LONG_LIQUIDATION":  "Longs being liquidated — price falling as OI drops",
    }.get(signal, "Unknown")


def run(**kwargs):
    spike_threshold_pct   = float(kwargs.get("spike_threshold_pct",   10.0))
    extreme_threshold_pct = float(kwargs.get("extreme_threshold_pct", 25.0))
    lookback_hours        = int(kwargs.get("lookback_hours",           1))
    auto_pause            = bool(kwargs.get("auto_pause",              False))
    top_n                 = int(kwargs.get("top_n",                    20))
    resume_normal         = bool(kwargs.get("resume_normal",           True))

    now_str  = datetime.now(timezone.utc).isoformat() + "Z"
    client   = DeltaClient(base_url=_BASE_URL)

    # Fetch current tickers
    try:
        tickers = client.tickers(contract_types="perpetual_futures")
        tickers.sort(
            key=lambda x: float(x.get("turnover_usd") or 0),
            reverse=True,
        )
        tickers = tickers[:top_n]
    except Exception as e:
        return f"OI Spike Detector: Failed to fetch tickers — {e}"

    if not tickers:
        return "OI Spike Detector: No tickers returned."

    # Load previous OI snapshot from app_settings for comparison
    prev_oi: Dict[str, float] = {}
    try:
        with connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value_json FROM app_settings WHERE key=?",
                (_OI_SPIKE_KEY,),
            ).fetchone()
            if row:
                stored = json.loads(row["value_json"])
                prev_oi = stored.get("oi_snapshot", {})
    except Exception:
        pass

    # Build current OI snapshot and detect spikes
    current_oi: Dict[str, float] = {}
    spikes:     List[dict]       = []
    normal:     List[str]        = []
    errors:     List[str]        = []

    for t in tickers:
        sym = t.get("symbol", "")
        if not sym:
            continue

        oi_val       = float(t.get("oi_value_usd") or
                             t.get("open_interest") or 0)
        mark_price   = float(t.get("mark_price")   or
                             t.get("close")         or 0)
        price_change = float(t.get("change_24h")   or 0)

        current_oi[sym] = oi_val

        if sym not in prev_oi or prev_oi[sym] == 0:
            # No previous snapshot — cannot calculate change yet
            continue

        oi_change_pct = _pct_change(prev_oi[sym], oi_val)

        if abs(oi_change_pct) < spike_threshold_pct:
            normal.append(sym)
            continue

        signal = _oi_signal(oi_change_pct, price_change)

        spikes.append({
            "symbol":        sym,
            "oi_prev":       prev_oi[sym],
            "oi_current":    oi_val,
            "oi_change_pct": round(oi_change_pct, 2),
            "price_change":  round(price_change,  4),
            "mark_price":    mark_price,
            "signal":        signal,
            "extreme":       abs(oi_change_pct) >= extreme_threshold_pct,
        })

    # Save updated OI snapshot to app_settings
    snapshot_payload = json.dumps({
        "oi_snapshot": current_oi,
        "updated_at":  now_str,
        "spike_threshold_pct":   spike_threshold_pct,
        "extreme_threshold_pct": extreme_threshold_pct,
    })
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value_json) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (_OI_SPIKE_KEY, snapshot_payload),
            )
    except Exception as e:
        errors.append(f"ERR | app_settings write failed — {e}")

    # No previous snapshot on first run
    if not prev_oi:
        return (
            "OI Spike Detector: First run — OI snapshot saved. "
            f"Monitoring {len(current_oi)} symbols. "
            f"Spikes will be detected on the next run."
        )

    messages = []
    paused   = 0
    resumed  = 0

    # Process spikes
    extreme_symbols = {s["symbol"] for s in spikes if s["extreme"]}
    spike_symbols   = {s["symbol"] for s in spikes}

    for spike in sorted(spikes, key=lambda x: abs(x["oi_change_pct"]), reverse=True):
        sym           = spike["symbol"]
        oi_change_pct = spike["oi_change_pct"]
        signal        = spike["signal"]
        extreme       = spike["extreme"]
        description   = _signal_description(signal)

        severity = "EXTREME" if extreme else "SPIKE"
        messages.append(
            f"{severity} | {sym}: OI {oi_change_pct:+.2f}% "
            f"price {spike['price_change']:+.4f}% "
            f"mark=${spike['mark_price']:.4f} "
            f"-> {signal}"
        )
        messages.append(f"  {description}")

        # Log to deployment_events for all bots on this symbol
        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                bots = conn.execute(
                    "SELECT id, name FROM deployments "
                    "WHERE symbol=? AND status='running'",
                    (sym,),
                ).fetchall()

            for bot in bots:
                try:
                    with connect() as conn:
                        conn.execute(
                            "INSERT INTO deployment_events"
                            "(deployment_id, ts, kind, message) "
                            "VALUES (?, ?, 'oi_spike', ?)",
                            (
                                bot["id"], now_str,
                                f"OI {severity}: {oi_change_pct:+.2f}% change "
                                f"on {sym} — {signal}: {description}",
                            ),
                        )
                except Exception as e:
                    errors.append(
                        f"ERR | {bot['name']}: event log failed — {e}"
                    )

        except Exception as e:
            errors.append(f"ERR | {sym}: bot lookup failed — {e}")

        # Auto-pause bots on extreme OI symbols
        if extreme and auto_pause:
            try:
                with connect() as conn:
                    conn.row_factory = sqlite3.Row
                    flat_bots = conn.execute(
                        "SELECT id, name FROM deployments "
                        "WHERE symbol=? "
                        "AND status='running' "
                        "AND open_side IS NULL",
                        (sym,),
                    ).fetchall()

                for bot in flat_bots:
                    try:
                        with connect() as conn:
                            conn.execute(
                                "UPDATE deployments "
                                "SET status='paused' WHERE id=?",
                                (bot["id"],),
                            )
                        with connect() as conn:
                            conn.execute(
                                "INSERT INTO deployment_events"
                                "(deployment_id, ts, kind, message) "
                                "VALUES (?, ?, 'oi_spike', ?)",
                                (
                                    bot["id"], now_str,
                                    f"Paused — extreme OI spike "
                                    f"{oi_change_pct:+.2f}% on {sym} "
                                    f"({signal}). Prevents entry into "
                                    f"potentially volatile move.",
                                ),
                            )
                        paused += 1
                        messages.append(
                            f"  Paused: {bot['name']} "
                            f"— extreme OI spike on {sym}"
                        )
                    except Exception as e:
                        errors.append(
                            f"ERR | {bot['name']}: pause failed — {e}"
                        )

            except Exception as e:
                errors.append(f"ERR | {sym}: pause lookup failed — {e}")

    # Auto-resume bots on symbols where OI has normalised
    if resume_normal and auto_pause:
        try:
            with connect() as conn:
                conn.row_factory = sqlite3.Row
                paused_bots = conn.execute(
                    "SELECT id, name, symbol FROM deployments "
                    "WHERE status='paused' AND open_side IS NULL"
                ).fetchall()

            for bot in paused_bots:
                if bot["symbol"] not in extreme_symbols:
                    try:
                        with connect() as conn:
                            conn.execute(
                                "UPDATE deployments "
                                "SET status='running' WHERE id=?",
                                (bot["id"],),
                            )
                        with connect() as conn:
                            conn.execute(
                                "INSERT INTO deployment_events"
                                "(deployment_id, ts, kind, message) "
                                "VALUES (?, ?, 'oi_spike', ?)",
                                (
                                    bot["id"], now_str,
                                    f"Resumed — OI on {bot['symbol']} "
                                    f"back within normal range "
                                    f"(threshold={extreme_threshold_pct:.1f}%)",
                                ),
                            )
                        resumed += 1
                        messages.append(
                            f"  Resumed: {bot['name']} ({bot['symbol']}) "
                            f"— OI normalised"
                        )
                    except Exception as e:
                        errors.append(
                            f"ERR | {bot['name']}: resume failed — {e}"
                        )

        except Exception as e:
            errors.append(f"ERR | resume scan failed — {e}")

    # Build report
    lines = [
        "Open Interest Spike Detector",
        f"  Symbols scanned  : {len(current_oi)}",
        f"  Spike threshold  : {spike_threshold_pct:.1f}%",
        f"  Extreme threshold: {extreme_threshold_pct:.1f}%",
        f"  Lookback         : {lookback_hours}h (vs previous snapshot)",
        f"  Spikes detected  : {len(spikes)}",
        f"  Extreme spikes   : {len(extreme_symbols)}",
        f"  Normal symbols   : {len(normal)}",
        "",
    ]

    if not spikes:
        lines.append(
            f"All {len(normal)} symbols have normal OI levels "
            f"(change < {spike_threshold_pct:.1f}%)."
        )
    else:
        lines.append("OI Spike Events:")
        lines.extend(f"  {m}" for m in messages
                     if not m.startswith("  Paused") and
                        not m.startswith("  Resumed"))
        lines.append("")

    if paused > 0 or resumed > 0:
        lines.append(
            f"Bot Actions: paused={paused}, resumed={resumed}"
        )
        action_msgs = [m for m in messages
                       if m.startswith("  Paused") or
                          m.startswith("  Resumed")]
        lines.extend(action_msgs)

    if not auto_pause and extreme_symbols:
        lines.append("")
        lines.append(
            f"Note: {len(extreme_symbols)} extreme OI spike(s) detected. "
            f"Set auto_pause=true in params_json to automatically "
            f"pause bots on affected symbols."
        )

    lines.append("")
    lines.append(
        f"OI snapshot saved to app_settings key='{_OI_SPIKE_KEY}'. "
        f"Next run will compare against this snapshot."
    )

    if errors:
        lines.append("")
        lines.append("Warnings/Errors:")
        lines.extend(f"  {e}" for e in errors)

    return "### OI Spike Detector\n\n" + "\n".join(lines)

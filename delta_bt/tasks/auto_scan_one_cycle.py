"""Auto-Scan One-Cycle Trade Bot.

Each scheduler tick performs a FULL market scan, selects the SINGLE BEST
setup (ranked by composite score), and deploys a one-cycle bot — a bot
that AUTOMATICALLY STOPS after its first closed trade (TP or SL hit).

Lifecycle per cycle:
  1. Fetch top N symbols by USD turnover
  2. Scan each symbol × resolution × strategy in parallel
  3. Score and rank all setups (win_rate + pnl_factor + trade_count)
  4. Pick the top-1 setup (or top-N if max_trades > 1)
  5. Skip if a one-cycle bot already running for that symbol+strategy
  6. Deploy deployment row tagged "one_cycle" with status='running'
     — the scheduler's one-cycle watchdog will set status='stopped'
       once the bot's first trade closes

Kwargs:
    venue               (str,   default "paper")   — Execution venue.
    strategy            (str,   default "auto")     — "auto" scans all known
                                                      strategies; or a specific
                                                      strategy name.
    resolutions         (list,  default ["15m","1h"]) — Timeframes to scan.
    top_n_symbols       (int,   default 20)         — Number of symbols to scan.
    max_trades          (int,   default 1)          — Max simultaneous one-cycle
                                                      trades per run.
    base_lot_size       (int,   default 1)          — Lot size per trade.
    sl_pct              (float, default 1.5)        — Stop-loss %.
    tp_pct              (float, default 3.0)        — Take-profit %.
    trail_pct           (float, default 0.0)        — Trailing stop %.
                                                      0 disables trailing.
    trail_activate_pct  (float, default 1.0)        — Profit % before trail kicks in.
    lookback_days       (int,   default 7)          — Signal detection window.
    profit_lookback_days(int,   default 30)         — Profitability filter window.
    min_win_rate        (float, default 0.45)       — Minimum win rate threshold.
    min_pnl             (float, default 0.0)        — Minimum 30-day PnL threshold.
    dry_run             (bool,  default False)      — Log only, do not deploy.
    workers             (int,   default 8)          — Parallel scan threads.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from delta_bt.data.delta_client import DeltaClient
from delta_bt.scanner.days_scanner import scan_strategy_setups, ScannerSetup
from delta_bt.store.db import connect

# ── Strategy universe scanned when strategy="auto" ────────────────────────────
_AUTO_STRATEGIES = [
    "ema3", "macd", "rsi_mr", "rsi_divergence",
    "momentum_breakout", "donchian_breakout", "atr_channel_breakout",
    "stochastic_rsi", "keltner_squeeze",
    "smc_ob", "smc_ob_fvg", "smc_liquidity_sweep", "smc_bos_retest",
    "supertrend_mom", "vwap", "obv_trend",
]

_VALID_VENUES = {"live", "testnet", "paper", "paper_live"}


def _to_bool(val, default: bool = False) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "1", "yes")


def _score(s: ScannerSetup) -> float:
    """Composite rank score — higher is better.
    Components:
      • win_rate  (0–1)  × 50  → up to 50 pts
      • pnl_norm           → up to 30 pts  (soft-capped at PnL=100)
      • trade_count_bonus  → up to 20 pts  (log-scaled, max at ~150 trades)
    """
    import math
    wr_score    = s.win_rate * 50.0
    pnl_score   = min(s.total_pnl / 100.0, 1.0) * 30.0
    trade_score = min(math.log1p(s.trade_count) / math.log1p(150), 1.0) * 20.0
    return wr_score + pnl_score + trade_score


def _already_running_one_cycle(conn, symbol: str, strategy: str) -> bool:
    """True if a one-cycle bot for this symbol+strategy is still running."""
    row = conn.execute(
        """
        SELECT id FROM deployments
        WHERE symbol   = ?
          AND strategy = ?
          AND tag      = 'one_cycle'
          AND status   = 'running'
        """,
        (symbol, strategy),
    ).fetchone()
    return row is not None


def run(**kwargs) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Parse kwargs ──────────────────────────────────────────────────────────
    venue               = str(kwargs.get("venue", "paper")).lower()
    if venue not in _VALID_VENUES:
        return (
            f"### Auto-Scan One-Cycle\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Invalid venue '{venue}'. "
            f"Valid options: {', '.join(sorted(_VALID_VENUES))}"
        )

    strategy_arg        = str(kwargs.get("strategy", "auto")).lower()
    top_n               = max(1, int(kwargs.get("top_n_symbols", 20)))
    max_trades          = max(1, int(kwargs.get("max_trades", 1)))
    base_size           = max(1, int(kwargs.get("base_lot_size", 1)))
    sl_pct              = float(kwargs.get("sl_pct", 1.5))
    tp_pct              = float(kwargs.get("tp_pct", 3.0))
    trail_pct           = float(kwargs.get("trail_pct", 0.0))
    trail_activate_pct  = float(kwargs.get("trail_activate_pct", 1.0))
    lookback_days       = int(kwargs.get("lookback_days", 7))
    profit_lookback_days= int(kwargs.get("profit_lookback_days", 30))
    min_win_rate        = float(kwargs.get("min_win_rate", 0.45))
    min_pnl             = float(kwargs.get("min_pnl", 0.0))
    dry_run             = _to_bool(kwargs.get("dry_run", False))
    workers             = int(kwargs.get("workers", 8))

    raw_res = kwargs.get("resolutions", ["15m", "1h"])
    if isinstance(raw_res, str):
        resolutions = [r.strip() for r in raw_res.split(",") if r.strip()]
    else:
        resolutions = list(raw_res)

    strategies = (
        _AUTO_STRATEGIES
        if strategy_arg == "auto"
        else [strategy_arg]
    )

    # ── Fetch top-N symbols ───────────────────────────────────────────────────
    client = DeltaClient(base_url="https://api.india.delta.exchange")
    try:
        tickers = client.tickers(contract_types="perpetual_futures")
    except Exception as e:
        return (
            f"### Auto-Scan One-Cycle\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Ticker fetch failed: {e}"
        )

    # Support custom symbol list override
    user_symbols_raw = kwargs.get("symbols") or kwargs.get("symbol_list")
    if isinstance(user_symbols_raw, str):
        symbols = [s.strip() for s in user_symbols_raw.split(",") if s.strip()]
    elif isinstance(user_symbols_raw, list):
        symbols = [str(s).strip() for s in user_symbols_raw if str(s).strip()]
    else:
        tickers.sort(
            key=lambda x: float(x.get("turnover_usd") or x.get("turnover") or 0),
            reverse=True,
        )
        symbols = [t["symbol"] for t in tickers[:top_n] if "symbol" in t]

    if not symbols:
        return (
            f"### Auto-Scan One-Cycle\n\n"
            f"Date: {now_str}\n\nWARN | No symbols returned."
        )

    # ── Run parallel scan ─────────────────────────────────────────────────────
    try:
        raw_setups: List[ScannerSetup] = scan_strategy_setups(
            client=client,
            symbols=symbols,
            resolutions=resolutions,
            strategies=strategies,
            workers=workers,
            lookback_days=lookback_days,
            profit_lookback_days=profit_lookback_days,
            min_win_rate=min_win_rate,
        )
    except Exception as e:
        return (
            f"### Auto-Scan One-Cycle\n\n"
            f"Date: {now_str}\n\n"
            f"ERR | Scanner failed: {e}"
        )

    # ── Apply extra filters ───────────────────────────────────────────────────
    setups = [s for s in raw_setups if s.total_pnl >= min_pnl]

    if not setups:
        return (
            f"### Auto-Scan One-Cycle\n\n"
            f"Date: {now_str}\n\n"
            f"Scanned {len(symbols)} symbols × {len(resolutions)} resolutions "
            f"× {len(strategies)} strategies. "
            f"No qualifying setups found."
        )

    # ── Rank setups ───────────────────────────────────────────────────────────
    setups.sort(key=_score, reverse=True)

    lines = [
        f"### Auto-Scan One-Cycle\n\n"
        f"Date          : {now_str}\n"
        f"Venue         : {venue}\n"
        f"Symbols       : {len(symbols)}\n"
        f"Strategies    : {len(strategies)}\n"
        f"Total Setups  : {len(setups)}\n"
        f"Max Trades    : {max_trades}\n"
        f"Dry Run       : {'yes' if dry_run else 'no'}\n"
    ]

    # ── Show top candidates ───────────────────────────────────────────────────
    lines.append("#### Top Candidates (ranked by score)\n")
    for rank, s in enumerate(setups[:10], 1):
        lines.append(
            f"  #{rank:2d} | {s.signal:<5} {s.symbol:<16} {s.strategy:<25} "
            f"{s.resolution:<4} @ {s.price:.4f} | "
            f"WR={s.win_rate:.0%}  PnL={s.total_pnl:.2f}  "
            f"Trades={s.trade_count}  Score={_score(s):.1f}"
        )

    # ── Deploy top-N one-cycle trades ─────────────────────────────────────────
    deployed = 0
    skipped  = 0

    lines.append("\n#### Deployment Results\n")

    # Exposure gate: block new entries while gross exposure >= limit
    from delta_bt.tasks.exposure_gate import exposure_blocked
    _blocked, _reason = exposure_blocked()
    if _blocked and not dry_run:
        lines.append(f"  ⛔ BLOCKED | {_reason}")
        setups = []

    with connect() as conn:
        for s in setups:
            if deployed >= max_trades:
                break

            # Skip if one-cycle bot already active for this pair+strategy
            if _already_running_one_cycle(conn, s.symbol, s.strategy):
                skipped += 1
                lines.append(
                    f"  ⏭  SKIP | {s.symbol} {s.strategy} — "
                    f"one-cycle bot already running."
                )
                continue

            now = datetime.now(timezone.utc).isoformat() + "Z"
            name = f"1C {s.signal} {s.symbol} {s.strategy} {s.resolution}"

            if dry_run:
                lines.append(
                    f"  🔬 DRY  | Would deploy: {name}\n"
                    f"         venue={venue}  size={base_size}  "
                    f"sl={sl_pct}%  tp={tp_pct}%  trail={trail_pct}%\n"
                    f"         WR={s.win_rate:.0%}  PnL={s.total_pnl:.2f}  "
                    f"Score={_score(s):.1f}"
                )
                deployed += 1
                continue

            # Force the signal direction via force_entry + params
            force_side = "buy" if s.signal in ("BUY", "LONG") else "sell"
            params_str = json.dumps({
                "force_entry_side": force_side,
                "one_cycle": True,      # hint for scheduler watchdog
            })

            try:
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
                        base_size, params_str,
                        sl_pct, tp_pct, trail_pct,
                        trail_activate_pct, 0.0,
                        0,   # reduce_only = False (opening trade)
                        60,  # tight 60s polling for quick exit
                        1 if venue == "live" else 0,
                        1,   # leverage
                        1,   # sync_leverage
                        1,   # force_entry on the detected signal side
                        now, now,
                        "one_cycle",
                    ),
                )
                dep_id = info.lastrowid

                conn.execute(
                    "INSERT INTO deployment_events"
                    "(deployment_id, ts, kind, message) "
                    "VALUES (?, ?, 'start', ?)",
                    (
                        dep_id, now,
                        f"one-cycle auto-deployed by scanner "
                        f"(score={_score(s):.1f}, WR={s.win_rate:.0%})",
                    ),
                )
                conn.commit()

                deployed += 1
                lines.append(
                    f"  ✅ DEPLOYED Bot #{dep_id} — {name}\n"
                    f"     venue={venue}  size={base_size}  "
                    f"SL={sl_pct}%  TP={tp_pct}%"
                    + (f"  Trail={trail_pct}% (after +{trail_activate_pct}%)"
                       if trail_pct > 0 else "") + "\n"
                    f"     WR={s.win_rate:.0%}  PnL={s.total_pnl:.2f}  "
                    f"Score={_score(s):.1f}  Side={force_side.upper()}"
                )

            except Exception as e:
                lines.append(
                    f"  ❌ ERR  | Failed to deploy {s.symbol} "
                    f"{s.strategy}: {e}"
                )

    lines.append(
        f"\n---\n"
        f"Deployed: {deployed}  |  Skipped (already running): {skipped}"
    )

    return "\n\n".join(lines)

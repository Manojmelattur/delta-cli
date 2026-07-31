"""Report generator — CSVs + JSON summary + text summary."""
from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import asdict
from datetime import datetime
from typing import Dict

from ..execution.portfolio import Portfolio


def _sharpe(returns, rf: float = 0.0, periods_per_year: int = 365 * 24 * 60):
    if len(returns) < 2:
        return 0.0
    import statistics as st
    mu = st.fmean(returns) - rf
    sd = st.pstdev(returns)
    if sd == 0:
        return 0.0
    return (mu / sd) * math.sqrt(periods_per_year)


def _max_drawdown(equity):
    peak = -float("inf")
    dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd = min(dd, (e - peak) / peak)
    return dd


def _streaks(trades):
    win_s = loss_s = cur = 0
    last = 0
    for t in trades:
        sign = 1 if t.pnl > 0 else -1
        cur = cur + sign if sign == last else sign
        last = sign
        if cur > 0: win_s = max(win_s, cur)
        else:       loss_s = min(loss_s, cur)
    return win_s, abs(loss_s)


def summarize(pf: Portfolio) -> Dict:
    eq_vals = [p.equity for p in pf.equity_curve]
    if not eq_vals:
        return {"error": "no equity points"}
    start = pf.starting_cash
    end = eq_vals[-1]
    rets = [(eq_vals[i] / eq_vals[i - 1]) - 1 for i in range(1, len(eq_vals))
            if eq_vals[i - 1] > 0]
    wins = [t for t in pf.trades if t.pnl > 0]
    losses = [t for t in pf.trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses) or 1e-9
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (-gross_loss / len(losses)) if losses else 0.0
    win_rate = (len(wins) / len(pf.trades)) if pf.trades else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    # exit-reason distribution (from exit fills)
    exits = [f for f in pf.fills if f.tag not in ("entry",)]
    exit_reasons: Dict[str, int] = {}
    for f in exits:
        exit_reasons[f.tag] = exit_reasons.get(f.tag, 0) + 1

    hold_bars = []
    for t in pf.trades:
        try:
            hold_bars.append((t.exit_ts - t.entry_ts).total_seconds())
        except Exception:
            pass
    avg_hold_s = (sum(hold_bars) / len(hold_bars)) if hold_bars else 0.0

    best = max(pf.trades, key=lambda t: t.pnl, default=None)
    worst = min(pf.trades, key=lambda t: t.pnl, default=None)
    win_streak, loss_streak = _streaks(pf.trades)

    return {
        "starting_capital": start,
        "ending_equity": end,
        "net_pnl": end - start,
        "return_pct": (end / start - 1) * 100 if start else 0,
        "trades": len(pf.trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": win_rate * 100,
        "profit_factor": gross_win / gross_loss,
        "avg_trade_pnl": (sum(t.pnl for t in pf.trades) / len(pf.trades)) if pf.trades else 0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "max_drawdown_pct": _max_drawdown(eq_vals) * 100,
        "sharpe": _sharpe(rets),
        "total_fees": sum(t.fees for t in pf.trades),
        "bars": len(pf.equity_curve),
        "exit_reasons": exit_reasons,
        "avg_hold_seconds": avg_hold_s,
        "best_trade_pnl": best.pnl if best else 0.0,
        "worst_trade_pnl": worst.pnl if worst else 0.0,
        "max_win_streak": win_streak,
        "max_loss_streak": loss_streak,
    }



def _dt(v):
    return v.isoformat() if isinstance(v, datetime) else v


def write_report(pf: Portfolio, out_dir: str, meta: Dict) -> Dict:
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "trades.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trade_id", "symbol", "side", "qty", "entry_ts", "entry_price",
                    "exit_ts", "exit_price", "pnl", "fees", "return_pct"])
        for t in pf.trades:
            w.writerow([t.trade_id, t.symbol, t.side.value, t.qty,
                        _dt(t.entry_ts), t.entry_price,
                        _dt(t.exit_ts), t.exit_price,
                        f"{t.pnl:.6f}", f"{t.fees:.6f}",
                        f"{t.return_pct * 100:.4f}"])


    with open(os.path.join(out_dir, "equity.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "equity", "cash", "position_value"])
        for e in pf.equity_curve:
            w.writerow([_dt(e.ts), f"{e.equity:.6f}",
                        f"{e.cash:.6f}", f"{e.position_value:.6f}"])

    with open(os.path.join(out_dir, "fills.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "symbol", "side", "qty", "price", "fee", "tag"])
        for x in pf.fills:
            w.writerow([_dt(x.ts), x.symbol, x.side.value, x.qty,
                        x.price, x.fee, x.tag])

    # Optional diagnostics dump (ADX / regime / stop levels per bar).
    if getattr(pf, "diag", None):
        cols = list(pf.diag[0].keys())
        with open(os.path.join(out_dir, "diagnostics.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for row in pf.diag:
                w.writerow([dict(row).get(c, "") for c in cols])


    summary = summarize(pf)
    summary["meta"] = meta
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    # Persist to SQLite for cross-run comparison.
    try:
        from ..store.db import save_run
        run_id = os.path.basename(os.path.normpath(out_dir))
        db_path = save_run(run_id, pf, summary, meta)
        summary["db_path"] = db_path
        summary["run_id"] = run_id
    except Exception as e:  # pragma: no cover
        print(f"[store] SQLite save failed: {e}")


    exit_lines = ", ".join(f"{k}:{v}" for k, v in
                           sorted(summary.get("exit_reasons", {}).items())) or "—"
    hold_s = summary.get("avg_hold_seconds", 0.0)
    hold_h = hold_s / 3600.0
    lines = [
        "=" * 64,
        f"Delta Backtest / Paper report — {meta.get('mode','?')}",
        "=" * 64,
        f"Strategy      : {meta.get('strategy')}",
        f"Symbol / Res  : {meta.get('symbol')} @ {meta.get('resolution')}",
        f"Period        : {meta.get('start')} → {meta.get('end')}",
        f"Params        : {meta.get('params')}",
        f"Risk (SL/TP/Tr): {meta.get('sl_pct')}% / {meta.get('tp_pct')}% "
        f"/ {meta.get('trail_pct')}%   Leverage: {meta.get('leverage')}x",
        "-" * 64,
        f"Starting cap  : {summary['starting_capital']:.2f}",
        f"Ending equity : {summary['ending_equity']:.2f}",
        f"Net PnL       : {summary['net_pnl']:.2f} ({summary['return_pct']:.2f}%)",
        f"Trades        : {summary['trades']} "
        f"(W:{summary['wins']} L:{summary['losses']} WR:{summary['win_rate_pct']:.1f}%)",
        f"Avg win/loss  : {summary['avg_win']:.2f} / {summary['avg_loss']:.2f}",
        f"Expectancy    : {summary['expectancy']:.2f} per trade",
        f"Profit factor : {summary['profit_factor']:.2f}",
        f"Avg trade PnL : {summary['avg_trade_pnl']:.2f}",
        f"Best / Worst  : {summary['best_trade_pnl']:.2f} / {summary['worst_trade_pnl']:.2f}",
        f"Streaks (W/L) : {summary['max_win_streak']} / {summary['max_loss_streak']}",
        f"Avg hold time : {hold_h:.2f} h",
        f"Exit reasons  : {exit_lines}",
        f"Max drawdown  : {summary['max_drawdown_pct']:.2f}%",
        f"Sharpe        : {summary['sharpe']:.2f}",
        f"Total fees    : {summary['total_fees']:.2f}",
        "=" * 64,
        f"Artifacts     : {out_dir}",
    ]

    text = "\n".join(lines)
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    try:
        print("\n" + text)
    except UnicodeEncodeError:
        # Windows consoles default to cp1252 and choke on → / — etc.
        import sys
        sys.stdout.buffer.write(("\n" + text + "\n").encode("utf-8", errors="replace"))
    return summary

"""Render equity-curve plots for stored runs to PNG."""
from __future__ import annotations

import bisect
import os
from datetime import datetime
from typing import List, Optional, Tuple

from .db import connect, list_runs


def _load_equity(run_id: str, db_path: Optional[str] = None):
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT ts, equity FROM equity WHERE run_id=? ORDER BY ts", (run_id,)
        )
        rows = cur.fetchall()
        meta = conn.execute(
            "SELECT strategy, symbol, resolution, starting_cap, ending_equity, "
            "return_pct, max_dd_pct FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
    ts = [datetime.fromisoformat(r[0]) for r in rows]
    eq = [r[1] for r in rows]
    return ts, eq, meta


def _load_trades(run_id: str, db_path: Optional[str] = None):
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT side, entry_ts, exit_ts, pnl FROM trades "
            "WHERE run_id=? ORDER BY seq", (run_id,))
        return [(s, datetime.fromisoformat(a), datetime.fromisoformat(b), p)
                for s, a, b, p in cur.fetchall()]


def _nearest(ts_list: List[datetime], eq_list: List[float],
             when: datetime) -> Optional[Tuple[datetime, float]]:
    if not ts_list:
        return None
    i = bisect.bisect_left(ts_list, when)
    if i >= len(ts_list): i = len(ts_list) - 1
    # pick closer of i and i-1
    if i > 0 and abs((ts_list[i-1] - when).total_seconds()) < \
                 abs((ts_list[i]   - when).total_seconds()):
        i -= 1
    return ts_list[i], eq_list[i]


def plot_runs(run_ids: List[str], out_path: str,
              db_path: Optional[str] = None,
              normalize: bool = False,
              title: Optional[str] = None,
              markers: bool = False) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise SystemExit("matplotlib not installed. Run: pip install matplotlib") from e

    if not run_ids:
        raise SystemExit("no run_ids provided")

    fig, ax = plt.subplots(figsize=(11, 6))
    used_labels = set()

    def _lbl(name: str) -> Optional[str]:
        # only show each marker label once in the legend
        if name in used_labels: return None
        used_labels.add(name); return name

    for rid in run_ids:
        ts, eq, meta = _load_equity(rid, db_path)
        if not eq:
            print(f"[plot] skipping {rid}: no equity rows"); continue
        label = rid
        if meta:
            label = f"{meta[0]} · {meta[1]} {meta[2]} · ret {meta[5]:.1f}%"

        y = eq
        if normalize and eq[0]:
            y = [v / eq[0] * 100.0 for v in eq]
        (line,) = ax.plot(ts, y, label=label, linewidth=1.4)

        if markers:
            trades = _load_trades(rid, db_path)
            long_x, long_y, short_x, short_y = [], [], [], []
            win_x, win_y, loss_x, loss_y = [], [], [], []
            for side, ent, exi, pnl in trades:
                e_pt = _nearest(ts, y, ent)
                x_pt = _nearest(ts, y, exi)
                if e_pt:
                    if side.upper() == "LONG":
                        long_x.append(e_pt[0]); long_y.append(e_pt[1])
                    else:
                        short_x.append(e_pt[0]); short_y.append(e_pt[1])
                if x_pt:
                    if pnl > 0:
                        win_x.append(x_pt[0]); win_y.append(x_pt[1])
                    else:
                        loss_x.append(x_pt[0]); loss_y.append(x_pt[1])
            ax.scatter(long_x, long_y, marker="^", s=42,
                       color="#22c55e", edgecolors="black", linewidths=0.4,
                       zorder=3, label=_lbl("entry long"))
            ax.scatter(short_x, short_y, marker="v", s=42,
                       color="#f97316", edgecolors="black", linewidths=0.4,
                       zorder=3, label=_lbl("entry short"))
            ax.scatter(win_x, win_y, marker="o", s=32,
                       color="#16a34a", edgecolors="black", linewidths=0.4,
                       zorder=4, label=_lbl("exit win"))
            ax.scatter(loss_x, loss_y, marker="x", s=42,
                       color="#dc2626", linewidths=1.6,
                       zorder=4, label=_lbl("exit loss"))

    ax.set_title(title or ("Equity curve (normalized to 100)" if normalize
                           else "Equity curve"))
    ax.set_xlabel("Time (UTC)")
    ax.set_ylabel("Equity (%)" if normalize else "Equity")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.autofmt_xdate()

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def resolve_run_ids(run_ids: List[str],
                    strategy: Optional[str] = None,
                    symbol: Optional[str] = None,
                    last: Optional[int] = None,
                    db_path: Optional[str] = None) -> List[str]:
    """If explicit run_ids given, use them. Otherwise select the most recent
    `last` runs matching optional filters."""
    if run_ids:
        return run_ids
    rows = list_runs(limit=last or 5, strategy=strategy,
                     symbol=symbol, db_path=db_path)
    return [r["run_id"] for r in rows]

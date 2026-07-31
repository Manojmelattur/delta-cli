"""Render ADX / regime / stop-level chart for a single run.

Reads `diagnostics.csv` (produced when a backtest is run with
`--diagnostics`) from the run's report directory.

Chart layout:
  Top panel   : price + entry/exit markers + SL (red dashed), TP (green dashed),
                trail (orange dotted) overlaid only while a position is open.
                Regime is shown as a coloured background band
                (green = trend, red = range, grey = neutral / warmup).
  Bottom panel: ADX line with horizontal threshold lines (trend_min, range_max)
                and the same regime background band.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import List, Optional


REGIME_COLOR = {
    "trend":    "#22c55e",   # green
    "range":    "#ef4444",   # red
    "neutral":  "#9ca3af",   # grey
    "warmup":   "#e5e7eb",   # light grey
}


def _load(csv_path: str) -> List[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(row: dict, key: str) -> Optional[float]:
    v = dict(row).get(key, "")
    if v == "" or v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _regime_bare(reg: str) -> str:
    return reg.rstrip("!") if reg else ""


def plot_diagnostics(run_dir: str, out_path: Optional[str] = None,
                     title: Optional[str] = None) -> str:
    csv_path = os.path.join(run_dir, "diagnostics.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"diagnostics.csv not found in {run_dir}. "
            "Re-run the backtest with --diagnostics.")
    rows = _load(csv_path)
    if not rows:
        raise ValueError("diagnostics.csv is empty")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError as e:
        raise RuntimeError("matplotlib not installed — `pip install matplotlib`") from e

    ts       = [datetime.fromisoformat(r["ts"]) for r in rows]
    close    = [_f(r, "close") for r in rows]
    adx      = [_f(r, "adx") for r in rows]
    sl_px    = [_f(r, "sl_px") for r in rows]
    tp_px    = [_f(r, "tp_px") for r in rows]
    trail_px = [_f(r, "trail_px") for r in rows]
    regime   = [_regime_bare(dict(r).get("regime", "")) for r in rows]
    side     = [dict(r).get("position_side", "flat") for r in rows]

    trend_min = _f(rows[0], "trend_min") or 20.0
    range_max = _f(rows[0], "range_max") or 20.0

    # detect entry / exit bar indices from position_side transitions
    entries: list[tuple[datetime, float, str]] = []
    exits:   list[tuple[datetime, float]]      = []
    prev_side = "flat"
    for i, s in enumerate(side):
        if prev_side == "flat" and s in ("LONG", "SHORT"):
            entries.append((ts[i], close[i], s))
        elif prev_side in ("LONG", "SHORT") and s == "flat":
            exits.append((ts[i], close[i]))
        prev_side = s

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 8), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    # ---- regime background bands (drawn on both axes) ----
    # collapse contiguous same-regime runs into spans
    span_start = 0
    for i in range(1, len(regime) + 1):
        if i == len(regime) or regime[i] != regime[span_start]:
            reg = regime[span_start] or "warmup"
            color = REGIME_COLOR.get(reg, "#e5e7eb")
            for ax in (ax1, ax2):
                ax.axvspan(ts[span_start], ts[i - 1], color=color, alpha=0.08,
                           linewidth=0)
            span_start = i

    # ---- price panel ----
    ax1.plot(ts, close, color="#111827", linewidth=1.1, label="close")
    # stops only while a position is open — leave None gaps so matplotlib
    # breaks the line at flat bars automatically
    ax1.plot(ts, sl_px,    color="#dc2626", linewidth=1.0, linestyle="--", label="SL")
    ax1.plot(ts, tp_px,    color="#16a34a", linewidth=1.0, linestyle="--", label="TP")
    ax1.plot(ts, trail_px, color="#f59e0b", linewidth=1.0, linestyle=":",  label="trail")
    for t, p, s in entries:
        marker = "^" if s == "LONG" else "v"
        color  = "#16a34a" if s == "LONG" else "#dc2626"
        ax1.scatter([t], [p], marker=marker, s=70, color=color, zorder=5,
                    edgecolors="white", linewidths=0.8)
    for t, p in exits:
        ax1.scatter([t], [p], marker="o", s=45, facecolors="none",
                    edgecolors="#111827", linewidths=1.2, zorder=5)
    ax1.set_ylabel("price")
    ax1.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax1.grid(True, alpha=0.25)
    ax1.set_title(title or f"ADX / regime / stops — {os.path.basename(run_dir)}")

    # ---- ADX panel ----
    ax2.plot(ts, adx, color="#2563eb", linewidth=1.1, label="ADX")
    ax2.axhline(trend_min, color="#22c55e", linewidth=0.8, linestyle="--",
                label=f"trend ≥ {trend_min:g}")
    if abs(trend_min - range_max) > 1e-6:
        ax2.axhline(range_max, color="#ef4444", linewidth=0.8, linestyle="--",
                    label=f"range < {range_max:g}")
    ax2.set_ylabel("ADX")
    ax2.set_ylim(0, max(50, max((v for v in adx if v is not None), default=40) * 1.1))
    ax2.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax2.grid(True, alpha=0.25)

    for ax in (ax1, ax2):
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))

    plt.tight_layout()
    out = out_path or os.path.join(run_dir, "adx_regime.png")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out

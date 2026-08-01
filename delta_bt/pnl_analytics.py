"""PnL Analytics module for terminal performance analysis.

Queries SQLite store (runs, trades, deployments) to generate:
- Portfolio PnL summary
- Daily / Weekly / Monthly PnL breakdown
- Per-strategy PnL leaderboard
- Terminal ASCII equity curve
"""
from __future__ import annotations

from typing import Dict, List, Optional
from .store.db import connect, _resolve_db

import re

C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_GREEN   = "\033[1;32m"
C_CYAN    = "\033[1;36m"
C_YELLOW  = "\033[1;33m"
C_RED     = "\033[1;31m"
C_DIM     = "\033[2m"

_ANSI_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    """Remove ANSI color codes from string."""
    return _ANSI_REGEX.sub('', str(text))


import unicodedata

def visible_len(text: str) -> int:
    """Calculate length of string excluding invisible ANSI escape codes and accounting for wide unicode chars (emojis)."""
    clean_text = strip_ansi(text)
    length = 0
    for char in clean_text:
        if unicodedata.east_asian_width(char) in ('W', 'F'):
            length += 2
        else:
            length += 1
    # Variation selectors (like U+FE0F in ⏸️) have length 1 in the loop but width 0 visually if attached to another char.
    # A simple way to handle the most common ones without a heavy library is to just subtract their count.
    length -= clean_text.count('\uFE0F')
    return length


import math


def format_pnl(val: Optional[float], color: bool = True, decimals: int = 2, prefix_symbol: str = "$") -> str:
    """Format PnL value with compact notation for large numbers, proper sign placing, and ANSI colors."""
    if val is None or math.isnan(val):
        val = 0.0

    abs_val = abs(val)
    if abs_val >= 1e12:
        num_str = f"{abs_val:.2e}"
    elif abs_val >= 1e9:
        num_str = f"{abs_val / 1e9:,.2f}B"
    elif abs_val >= 1e6:
        num_str = f"{abs_val / 1e6:,.2f}M"
    elif abs_val >= 10000:
        num_str = f"{abs_val / 1e3:,.2f}K"
    else:
        num_str = f"{abs_val:,.{decimals}f}"

    if val > 0:
        formatted = f"+{prefix_symbol}{num_str}"
        return f"{C_GREEN}{formatted}{C_RESET}" if color else formatted
    elif val < 0:
        formatted = f"-{prefix_symbol}{num_str}"
        return f"{C_RED}{formatted}{C_RESET}" if color else formatted
    else:
        formatted = f"{prefix_symbol}0.{'0' * decimals}"
        return f"{C_DIM}{formatted}{C_RESET}" if color else formatted


def format_pct(val: Optional[float], color: bool = True, decimals: int = 1) -> str:
    """Format percentage value with compact notation for large values and ANSI colors."""
    if val is None or math.isnan(val):
        val = 0.0

    abs_val = abs(val)
    if abs_val >= 1e12:
        num_str = f"{abs_val:.2e}%"
    elif abs_val >= 1e9:
        num_str = f"{abs_val / 1e9:,.1f}B%"
    elif abs_val >= 1e6:
        num_str = f"{abs_val / 1e6:,.1f}M%"
    elif abs_val >= 10000:
        num_str = f"{abs_val / 1e3:,.1f}K%"
    else:
        num_str = f"{abs_val:.{decimals}f}%"

    if val > 0:
        formatted = f"+{num_str}"
        return f"{C_GREEN}{formatted}{C_RESET}" if color else formatted
    elif val < 0:
        formatted = f"-{num_str}"
        return f"{C_RED}{formatted}{C_RESET}" if color else formatted
    else:
        formatted = f"0.{'0' * decimals}%"
        return f"{C_DIM}{formatted}{C_RESET}" if color else formatted


def render_box_table(headers: List[str], rows: List[List[str]], title: Optional[str] = None) -> str:
    """Render minimalist plain table to prevent Unicode emoji misalignment."""
    if not headers:
        return ""

    # Calculate max column widths
    col_widths = [visible_len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], visible_len(cell))
                
    # Add a bit of padding to each column
    for i in range(len(col_widths)):
        col_widths[i] += 1

    # Headers
    hdr_str = ""
    for i, h in enumerate(headers):
        v_len = visible_len(h)
        pad = " " * (col_widths[i] - v_len)
        hdr_str += f" {C_BOLD}{h}{pad}{C_RESET}  "
        
    total_len = visible_len(hdr_str)

    lines = []
    if title:
        title_len = visible_len(title) + 4
        rem_len = max(0, total_len - title_len)
        lines.append(f"{C_CYAN}── {C_BOLD}{title.upper()}{C_RESET} {C_CYAN}{'─' * rem_len}{C_RESET}")
    else:
        lines.append(f"{C_CYAN}{'─' * total_len}{C_RESET}")

    lines.append(hdr_str)
    
    # Separator
    lines.append(f"{C_CYAN}{'─' * total_len}{C_RESET}")

    # Rows
    if not rows:
        lines.append("  (no records) ")
    else:
        for r in rows:
            row_str = ""
            for i, cell in enumerate(r):
                w = col_widths[i]
                v_len = visible_len(cell)
                pad = " " * (w - v_len)
                row_str += f" {cell}{pad}  "
            lines.append(row_str)

    lines.append(f"{C_CYAN}{'─' * visible_len(hdr_str)}{C_RESET}")
    return "\n".join(lines)


def generate_ascii_chart(points: List[float], width: int = 50, height: int = 8) -> str:
    """Render a clean ASCII chart for equity curves in the terminal."""
    if not points:
        return f"  {C_DIM}[No equity points recorded]{C_RESET}"
    
    if len(points) > width:
        step = len(points) / width
        sampled = [points[int(i * step)] for i in range(width)]
    else:
        sampled = points

    min_val, max_val = min(sampled), max(sampled)
    val_range = max_val - min_val if max_val != min_val else 1.0

    grid = [[" " for _ in range(len(sampled))] for _ in range(height)]
    
    for x, val in enumerate(sampled):
        y = int((val - min_val) / val_range * (height - 1))
        y = height - 1 - y
        grid[y][x] = "📈" if x == len(sampled) - 1 else "*"

    lines = []
    lines.append(f"  {C_CYAN}Max Equity:{C_RESET} {C_GREEN}${max_val:,.2f}{C_RESET}")
    for i, row in enumerate(grid):
        level = max_val - (i / (height - 1)) * val_range if height > 1 else max_val
        lines.append(f"  {level:>9.2f} │ {C_GREEN}" + "".join(row) + f"{C_RESET}")
    lines.append("            └" + "─" * len(sampled))
    lines.append(f"  {C_CYAN}Min Equity:{C_RESET} {C_RED}${min_val:,.2f}{C_RESET}")

    return "\n".join(lines)


def get_portfolio_pnl(db_path=None, venue=None, strategy=None, symbol=None, days=None):
    """Calculate aggregate portfolio PnL across all runs and deployments."""
    db_file = _resolve_db(db_path)
    
    conds_runs = []
    args_runs = []
    if venue: conds_runs.append("venue = ?"); args_runs.append(venue)
    if strategy: conds_runs.append("strategy = ?"); args_runs.append(strategy)
    if symbol: conds_runs.append("symbol = ?"); args_runs.append(symbol)
    if days: conds_runs.append("created_at >= datetime('now', '-' || ? || ' days')"); args_runs.append(days)
    where_runs = (" WHERE " + " AND ".join(conds_runs)) if conds_runs else ""

    conds_deps = []
    args_deps = []
    if venue: conds_deps.append("venue = ?"); args_deps.append(venue)
    if strategy: conds_deps.append("strategy = ?"); args_deps.append(strategy)
    if symbol: conds_deps.append("symbol = ?"); args_deps.append(symbol)
    if days: conds_deps.append("created_at >= datetime('now', '-' || ? || ' days')"); args_deps.append(days)
    where_deps = (" WHERE " + " AND ".join(conds_deps)) if conds_deps else ""

    conds_trades = []
    args_trades = []
    if venue: conds_trades.append("COALESCE(r.venue, d.venue) = ?"); args_trades.append(venue)
    if strategy: conds_trades.append("COALESCE(r.strategy, d.strategy) = ?"); args_trades.append(strategy)
    if symbol: conds_trades.append("t.symbol = ?"); args_trades.append(symbol)
    if days: conds_trades.append("t.exit_ts >= datetime('now', '-' || ? || ' days')"); args_trades.append(days)
    where_trades = (" WHERE " + " AND ".join(conds_trades)) if conds_trades else ""
    
    with connect(str(db_file)) as conn:
        run_stats = conn.execute(f"""
            SELECT 
                COUNT(*) as total_runs,
                COALESCE(SUM(starting_cap), 0) as start_cap,
                COALESCE(SUM(net_pnl), 0) as total_pnl,
                COALESCE(AVG(win_rate_pct), 0) as avg_winrate,
                COALESCE(AVG(sharpe), 0) as avg_sharpe,
                COALESCE(AVG(max_dd_pct), 0) as avg_max_dd,
                COALESCE(SUM(trades), 0) as total_trades
            FROM runs {where_runs}
        """, args_runs).fetchone()

        bot_stats = conn.execute(f"""
            SELECT 
                COUNT(*) as total_bots,
                COALESCE(SUM(realized_pnl), 0) as bot_pnl,
                COUNT(CASE WHEN status='running' THEN 1 END) as active_bots
            FROM deployments {where_deps}
        """, args_deps).fetchone()

        trade_stats = conn.execute(f"""
            SELECT 
                COUNT(*) as count,
                COUNT(CASE WHEN t.pnl > 0 THEN 1 END) as wins,
                COUNT(CASE WHEN t.pnl <= 0 THEN 1 END) as losses,
                COALESCE(SUM(t.pnl), 0) as net_pnl,
                COALESCE(MAX(t.pnl), 0) as max_win,
                COALESCE(MIN(t.pnl), 0) as max_loss,
                COALESCE(SUM(t.fees), 0) as total_fees
            FROM trades t
            LEFT JOIN runs r ON r.run_id = t.run_id
            LEFT JOIN deployments d ON ('d_' || d.id) = t.run_id
            {where_trades}
        """, args_trades).fetchone()

        equity_rows = conn.execute("SELECT equity FROM equity ORDER BY rowid ASC").fetchall()
        equity_pts = [r[0] for r in equity_rows if r[0] is not None]

    win_rate = (trade_stats[1] / trade_stats[0] * 100) if trade_stats[0] > 0 else run_stats[3]
    total_pnl = run_stats[2] + bot_stats[1]

    return {
        "total_runs": run_stats[0],
        "total_bots": bot_stats[0],
        "active_bots": bot_stats[2],
        "starting_capital": run_stats[1],
        "net_pnl": total_pnl,
        "total_trades": trade_stats[0] or run_stats[6],
        "winning_trades": trade_stats[1],
        "losing_trades": trade_stats[2],
        "win_rate_pct": win_rate,
        "best_trade_pnl": trade_stats[4],
        "worst_trade_pnl": trade_stats[5],
        "total_fees": trade_stats[6],
        "avg_sharpe": run_stats[4],
        "avg_max_dd_pct": run_stats[5],
        "equity_points": equity_pts
    }


def get_daily_pnl(limit=30, db_path=None, venue=None, strategy=None, symbol=None, days=None):
    """Calculate daily PnL breakdown from closed trades."""
    db_file = _resolve_db(db_path)
    
    conds_trades = ["t.exit_ts IS NOT NULL AND t.exit_ts != ''"]
    args_trades = []
    if venue: conds_trades.append("COALESCE(r.venue, d.venue) = ?"); args_trades.append(venue)
    if strategy: conds_trades.append("COALESCE(r.strategy, d.strategy) = ?"); args_trades.append(strategy)
    if symbol: conds_trades.append("t.symbol = ?"); args_trades.append(symbol)
    if days: conds_trades.append("t.exit_ts >= datetime('now', '-' || ? || ' days')"); args_trades.append(days)
    where_trades = (" WHERE " + " AND ".join(conds_trades))
    
    with connect(str(db_file)) as conn:
        rows = conn.execute(f"""
            SELECT 
                SUBSTR(t.exit_ts, 1, 10) as date,
                COUNT(*) as trades,
                COUNT(CASE WHEN t.pnl > 0 THEN 1 END) as wins,
                SUM(t.pnl) as daily_pnl,
                MAX(t.pnl) as max_win,
                MIN(t.pnl) as max_loss,
                SUM(t.fees) as fees
            FROM trades t
            LEFT JOIN runs r ON r.run_id = t.run_id
            LEFT JOIN deployments d ON ('d_' || d.id) = t.run_id
            {where_trades}
            GROUP BY SUBSTR(t.exit_ts, 1, 10)
            ORDER BY date DESC
            LIMIT ?
        """, args_trades + [limit]).fetchall()

    result = []
    for r in rows:
        trades = r[1]
        wins = r[2]
        wr = (wins / trades * 100) if trades > 0 else 0.0
        result.append({
            "date": r[0],
            "trades": trades,
            "wins": wins,
            "win_rate_pct": wr,
            "pnl": r[3] or 0.0,
            "max_win": r[4] or 0.0,
            "max_loss": r[5] or 0.0,
            "fees": r[6] or 0.0
        })
    return result


def get_strategy_pnl_breakdown(db_path=None, venue=None, strategy=None, symbol=None, days=None):
    """Calculate PnL breakdown grouped by strategy."""
    db_file = _resolve_db(db_path)
    
    conds_runs = []
    args_runs = []
    if venue: conds_runs.append("venue = ?"); args_runs.append(venue)
    if strategy: conds_runs.append("strategy = ?"); args_runs.append(strategy)
    if symbol: conds_runs.append("symbol = ?"); args_runs.append(symbol)
    if days: conds_runs.append("created_at >= datetime('now', '-' || ? || ' days')"); args_runs.append(days)
    where_runs = (" WHERE " + " AND ".join(conds_runs)) if conds_runs else ""
    
    with connect(str(db_file)) as conn:
        rows = conn.execute(f"""
            SELECT 
                strategy,
                COUNT(*) as total_runs,
                SUM(net_pnl) as total_pnl,
                AVG(win_rate_pct) as avg_winrate,
                AVG(sharpe) as avg_sharpe,
                AVG(max_dd_pct) as avg_max_dd,
                SUM(trades) as total_trades
            FROM runs
            {where_runs}
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """, args_runs).fetchall()

    out = []
    for r in rows:
        out.append({
            "strategy": r[0],
            "runs": r[1],
            "pnl": r[2] or 0.0,
            "win_rate_pct": r[3] or 0.0,
            "sharpe": r[4] or 0.0,
            "max_dd_pct": r[5] or 0.0,
            "trades": r[6] or 0
        })
    return out


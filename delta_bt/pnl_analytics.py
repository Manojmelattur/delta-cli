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


def visible_len(text: str) -> int:
    """Calculate length of string excluding invisible ANSI escape codes."""
    return len(strip_ansi(text))


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
    """Render minimalist Unicode box table with cyan borders and ANSI-aware column alignment."""
    if not headers:
        return ""

    col_widths = [visible_len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], visible_len(cell))

    top_border = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
    mid_border = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
    bot_border = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"

    lines = []
    if title:
        title_line = f"┌─ {title} "
        rem_len = max(0, sum(col_widths) + len(col_widths) * 3 - visible_len(title_line) + 1)
        lines.append(f"{C_CYAN}{title_line}{'─' * rem_len}┐{C_RESET}")
    else:
        lines.append(f"{C_CYAN}{top_border}{C_RESET}")

    # Headers
    hdr_str = f"{C_CYAN}│{C_RESET}"
    for i, h in enumerate(headers):
        v_len = visible_len(h)
        pad = " " * (col_widths[i] - v_len)
        hdr_str += f" {C_BOLD}{h}{pad}{C_RESET} {C_CYAN}│{C_RESET}"
    lines.append(hdr_str)
    lines.append(f"{C_CYAN}{mid_border}{C_RESET}")

    # Rows
    if not rows:
        empty_str = " (no records) ".center(sum(col_widths) + len(col_widths) * 3 - 1)
        lines.append(f"{C_CYAN}│{C_RESET}{C_DIM}{empty_str}{C_RESET}{C_CYAN}│{C_RESET}")
    else:
        for r in rows:
            row_str = f"{C_CYAN}│{C_RESET}"
            for i, cell in enumerate(r):
                w = col_widths[i]
                v_len = visible_len(cell)
                pad = " " * (w - v_len)
                row_str += f" {cell}{pad} {C_CYAN}│{C_RESET}"
            lines.append(row_str)

    lines.append(f"{C_CYAN}{bot_border}{C_RESET}")
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


def get_portfolio_pnl(db_path: Optional[str] = None) -> Dict:
    """Calculate aggregate portfolio PnL across all runs and deployments."""
    db_file = _resolve_db(db_path)
    with connect(str(db_file)) as conn:
        run_stats = conn.execute("""
            SELECT 
                COUNT(*) as total_runs,
                COALESCE(SUM(starting_cap), 0) as start_cap,
                COALESCE(SUM(net_pnl), 0) as total_pnl,
                COALESCE(AVG(win_rate_pct), 0) as avg_winrate,
                COALESCE(AVG(sharpe), 0) as avg_sharpe,
                COALESCE(AVG(max_dd_pct), 0) as avg_max_dd,
                COALESCE(SUM(trades), 0) as total_trades
            FROM runs
        """).fetchone()

        bot_stats = conn.execute("""
            SELECT 
                COUNT(*) as total_bots,
                COALESCE(SUM(realized_pnl), 0) as bot_pnl,
                COUNT(CASE WHEN status='running' THEN 1 END) as active_bots
            FROM deployments
        """).fetchone()

        trade_stats = conn.execute("""
            SELECT 
                COUNT(*) as count,
                COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins,
                COUNT(CASE WHEN pnl <= 0 THEN 1 END) as losses,
                COALESCE(SUM(pnl), 0) as net_pnl,
                COALESCE(MAX(pnl), 0) as max_win,
                COALESCE(MIN(pnl), 0) as max_loss,
                COALESCE(SUM(fees), 0) as total_fees
            FROM trades
        """).fetchone()

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


def get_daily_pnl(limit: int = 30, db_path: Optional[str] = None) -> List[Dict]:
    """Calculate daily PnL breakdown from closed trades."""
    db_file = _resolve_db(db_path)
    with connect(str(db_file)) as conn:
        rows = conn.execute("""
            SELECT 
                SUBSTR(exit_ts, 1, 10) as date,
                COUNT(*) as trades,
                COUNT(CASE WHEN pnl > 0 THEN 1 END) as wins,
                SUM(pnl) as daily_pnl,
                MAX(pnl) as max_win,
                MIN(pnl) as max_loss,
                SUM(fees) as fees
            FROM trades
            WHERE exit_ts IS NOT NULL AND exit_ts != ''
            GROUP BY SUBSTR(exit_ts, 1, 10)
            ORDER BY date DESC
            LIMIT ?
        """, (limit,)).fetchall()

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


def get_strategy_pnl_breakdown(db_path: Optional[str] = None) -> List[Dict]:
    """Calculate PnL breakdown grouped by strategy."""
    db_file = _resolve_db(db_path)
    with connect(str(db_file)) as conn:
        rows = conn.execute("""
            SELECT 
                strategy,
                COUNT(*) as total_runs,
                SUM(net_pnl) as total_pnl,
                AVG(win_rate_pct) as avg_winrate,
                AVG(sharpe) as avg_sharpe,
                AVG(max_dd_pct) as avg_max_dd,
                SUM(trades) as total_trades
            FROM runs
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """).fetchall()

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

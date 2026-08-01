import sys
import re

with open("delta_bt/pnl_analytics.py", "r") as f:
    code = f.read()

# Replace get_portfolio_pnl
def replace_func(func_name, code, new_func_body):
    start = code.find(f"def {func_name}(")
    if start == -1: return code
    end = code.find("\ndef ", start + 10)
    if end == -1: end = len(code)
    return code[:start] + new_func_body + "\n" + code[end:]

new_get_portfolio_pnl = """def get_portfolio_pnl(db_path=None, venue=None, strategy=None, symbol=None, days=None):
    \"\"\"Calculate aggregate portfolio PnL across all runs and deployments.\"\"\"
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
        run_stats = conn.execute(f\"\"\"
            SELECT 
                COUNT(*) as total_runs,
                COALESCE(SUM(starting_cap), 0) as start_cap,
                COALESCE(SUM(net_pnl), 0) as total_pnl,
                COALESCE(AVG(win_rate_pct), 0) as avg_winrate,
                COALESCE(AVG(sharpe), 0) as avg_sharpe,
                COALESCE(AVG(max_dd_pct), 0) as avg_max_dd,
                COALESCE(SUM(trades), 0) as total_trades
            FROM runs {where_runs}
        \"\"\", args_runs).fetchone()

        bot_stats = conn.execute(f\"\"\"
            SELECT 
                COUNT(*) as total_bots,
                COALESCE(SUM(realized_pnl), 0) as bot_pnl,
                COUNT(CASE WHEN status='running' THEN 1 END) as active_bots
            FROM deployments {where_deps}
        \"\"\", args_deps).fetchone()

        trade_stats = conn.execute(f\"\"\"
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
        \"\"\", args_trades).fetchone()

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
"""

new_get_daily_pnl = """def get_daily_pnl(limit=30, db_path=None, venue=None, strategy=None, symbol=None, days=None):
    \"\"\"Calculate daily PnL breakdown from closed trades.\"\"\"
    db_file = _resolve_db(db_path)
    
    conds_trades = ["t.exit_ts IS NOT NULL AND t.exit_ts != ''"]
    args_trades = []
    if venue: conds_trades.append("COALESCE(r.venue, d.venue) = ?"); args_trades.append(venue)
    if strategy: conds_trades.append("COALESCE(r.strategy, d.strategy) = ?"); args_trades.append(strategy)
    if symbol: conds_trades.append("t.symbol = ?"); args_trades.append(symbol)
    if days: conds_trades.append("t.exit_ts >= datetime('now', '-' || ? || ' days')"); args_trades.append(days)
    where_trades = (" WHERE " + " AND ".join(conds_trades))
    
    with connect(str(db_file)) as conn:
        rows = conn.execute(f\"\"\"
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
        \"\"\", args_trades + [limit]).fetchall()

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
"""

new_get_strategy_pnl = """def get_strategy_pnl_breakdown(db_path=None, venue=None, strategy=None, symbol=None, days=None):
    \"\"\"Calculate PnL breakdown grouped by strategy.\"\"\"
    db_file = _resolve_db(db_path)
    
    conds_runs = []
    args_runs = []
    if venue: conds_runs.append("venue = ?"); args_runs.append(venue)
    if strategy: conds_runs.append("strategy = ?"); args_runs.append(strategy)
    if symbol: conds_runs.append("symbol = ?"); args_runs.append(symbol)
    if days: conds_runs.append("created_at >= datetime('now', '-' || ? || ' days')"); args_runs.append(days)
    where_runs = (" WHERE " + " AND ".join(conds_runs)) if conds_runs else ""
    
    with connect(str(db_file)) as conn:
        rows = conn.execute(f\"\"\"
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
        \"\"\", args_runs).fetchall()

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
"""

code = replace_func("get_portfolio_pnl", code, new_get_portfolio_pnl)
code = replace_func("get_daily_pnl", code, new_get_daily_pnl)
code = replace_func("get_strategy_pnl_breakdown", code, new_get_strategy_pnl)

with open("delta_bt/pnl_analytics.py", "w") as f:
    f.write(code)
print("Updated delta_bt/pnl_analytics.py")

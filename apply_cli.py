import sys

with open("delta_bt/cli.py", "r") as f:
    code = f.read()

# 1. Update cmd_pnl signature
def replace_cmd_pnl():
    global code
    old_pnl = """def cmd_pnl(a) -> int:
    from .pnl_analytics import get_portfolio_pnl, get_daily_pnl, generate_ascii_chart, render_box_table, format_pnl
    summary = get_portfolio_pnl()"""
    new_pnl = """def cmd_pnl(a) -> int:
    from .pnl_analytics import get_portfolio_pnl, get_daily_pnl, generate_ascii_chart, render_box_table, format_pnl
    venue = getattr(a, 'venue', None)
    strategy = getattr(a, 'strategy', None)
    symbol = getattr(a, 'symbol', None)
    days = getattr(a, 'days', None)
    
    summary = get_portfolio_pnl(venue=venue, strategy=strategy, symbol=symbol, days=days)"""
    code = code.replace(old_pnl, new_pnl)

    old_daily = "daily = get_daily_pnl(limit=a.days)"
    new_daily = "daily = get_daily_pnl(limit=a.days or 30, venue=venue, strategy=strategy, symbol=symbol, days=days)"
    code = code.replace(old_daily, new_daily)

# 2. Update cmd_pnl_strategy
def replace_cmd_pnl_strategy():
    global code
    old_strat = """def cmd_pnl_strategy(_a) -> int:
    from .pnl_analytics import get_strategy_pnl_breakdown, render_box_table, format_pnl
    rows_data = get_strategy_pnl_breakdown()"""
    new_strat = """def cmd_pnl_strategy(a) -> int:
    from .pnl_analytics import get_strategy_pnl_breakdown, render_box_table, format_pnl
    venue = getattr(a, 'venue', None)
    strategy = getattr(a, 'strategy', None)
    symbol = getattr(a, 'symbol', None)
    days = getattr(a, 'days', None)
    rows_data = get_strategy_pnl_breakdown(venue=venue, strategy=strategy, symbol=symbol, days=days)"""
    code = code.replace(old_strat, new_strat)

# 3. Add arguments to parser
def add_args():
    global code
    old_args_pnl = """    # PnL & Analytics
    pn = sub.add_parser("pnl", help="Show portfolio PnL summary, win rate, and ASCII equity chart")
    pn.add_argument("--days", type=int, default=30, help="Number of daily breakdown rows to show")

    pns = sub.add_parser("pnl-strategy", help="Show performance breakdown per strategy")"""
    new_args_pnl = """    # PnL & Analytics
    pn = sub.add_parser("pnl", help="Show portfolio PnL summary, win rate, and ASCII equity chart")
    pn.add_argument("--days", type=int, default=None, help="Filter trades within last N days")
    pn.add_argument("--venue", default=None, help="Filter by venue")
    pn.add_argument("--strategy", default=None, help="Filter by strategy")
    pn.add_argument("--symbol", default=None, help="Filter by symbol")

    pns = sub.add_parser("pnl-strategy", help="Show performance breakdown per strategy")
    pns.add_argument("--days", type=int, default=None, help="Filter trades within last N days")
    pns.add_argument("--venue", default=None, help="Filter by venue")
    pns.add_argument("--strategy", default=None, help="Filter by strategy")
    pns.add_argument("--symbol", default=None, help="Filter by symbol")"""
    code = code.replace(old_args_pnl, new_args_pnl)

replace_cmd_pnl()
replace_cmd_pnl_strategy()
add_args()

with open("delta_bt/cli.py", "w") as f:
    f.write(code)
print("Updated delta_bt/cli.py")

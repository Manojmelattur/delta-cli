import sys

with open("delta_bt/cli.py", "r") as f:
    code = f.read()

# 1. Update cmd_pnl signature
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

# 4. Fix scan parser
old_scan_parser = """    sc = sub.add_parser(
        "scan", help="Backtest ALL strategies on one symbol/timeframe and rank them"
    )
    sc.add_argument("--symbol", required=True, help="e.g. BTCUSD, ETHUSD")
    sc.add_argument("--timeframe", "--resolution", dest="resolution", default="15m")"""

new_scan_parser = """    sc = sub.add_parser(
        "scan", help="Scan ALL strategies on one symbol, or ONE strategy across market universe"
    )
    sc.add_argument("--symbol", default=None, help="e.g. BTCUSD, ETHUSD")
    sc.add_argument("--strategy", default=None, help="Strategy to scan across the universe")
    sc.add_argument("--timeframe", "--resolution", dest="resolution", default="15m")"""
code = code.replace(old_scan_parser, new_scan_parser)

# 5. Fix cmd_scan
start_idx = code.find("def cmd_scan(a) -> int:")
end_idx = code.find("def cmd_serve(a) -> int:", start_idx)

new_cmd_scan = """def cmd_scan(a) -> int:
    \"\"\"Run every strategy against one symbol, OR run one strategy against many symbols.\"\"\"
    if not a.symbol and not a.strategy:
        print("You must provide either --symbol (to scan all strategies on an asset) or --strategy (to scan all assets for a strategy).", file=sys.stderr)
        return 2

    # --- resolve window ---
    if a.start and a.end:
        start, end = a.start, a.end
    else:
        end = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
        start = end - timedelta(days=a.days)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        print("invalid range", file=sys.stderr)
        return 2

    live = True if a.live is None else a.live
    base, _ = _resolve_urls(a, live=live)
    key, sec = _resolve_keys(a, live=live)
    client = DeltaClient(base, key, sec)

    cfg = RunConfig(
        strategy="_scan",
        symbol=a.symbol or "UNIVERSE",
        resolution=a.resolution,
        capital=a.capital,
        params={},
        start=start,
        end=end,
        fee_bps=a.fee_bps,
        slippage_bps=a.slippage_bps,
        qty_pct=a.qty_pct,
        sl_pct=a.sl_pct,
        tp_pct=a.tp_pct,
        trail_pct=a.trail_pct,
        leverage=a.leverage,
        adx_filter=a.adx_filter,
        adx_len=a.adx_len,
        adx_trend_min=a.adx_trend_min,
        adx_range_max=a.adx_range_max,
        adx_exit_on_flip=a.adx_exit_on_flip,
        adx_tighten_trail_on_flip=a.adx_tighten_trail_on_flip,
    )

    from .reports.report import summarize
    from .pnl_analytics import render_box_table

    if a.symbol and not a.strategy:
        # MODE 1: Scan all strategies against ONE symbol
        print(f"[scan] {a.symbol} @ {a.resolution}  {start.date()} → {end.date()}  venue={base}")
        bars = load_history(client, a.symbol, a.resolution, start, end)
        if not bars:
            print("no data returned; check symbol/timeframe/dates", file=sys.stderr)
            return 2
            
        print(f"[scan] {len(bars)} bars loaded — running {len(discover_strategies())} strategies")
        
        results = []
        table_rows = []
        for name in sorted(discover_strategies().keys()):
            try:
                strat = load_strategy(name, {})
                pf = run_backtest(bars, strat, cfg)
                s = summarize(pf)
                results.append({"strategy": name, "summary": s, "pf": pf})
                table_rows.append([
                    name, f"{s['return_pct']:.2f}%", str(s['trades']),
                    f"{s['win_rate_pct']:.1f}%", f"{s['profit_factor']:.2f}",
                    f"{s['max_drawdown_pct']:.2f}%", "✓ OK"
                ])
            except Exception as e:
                table_rows.append([name, "-", "-", "-", "-", "-", f"✗ ERROR: {e}"])
                
        headers = ["Strategy", "Return %", "Trades", "Win Rate %", "Profit Factor", "Max DD %", "Status"]
        print("\\n" + render_box_table(headers, table_rows, title=f"MARKET SCANNER ({a.symbol} @ {a.resolution})") + "\\n")
        
    elif a.strategy:
        # MODE 2: Scan ONE strategy against MANY symbols
        symbols = []
        if a.symbol:
            symbols = [a.symbol]
        else:
            print(f"[scan] Fetching top {a.top or 20} symbols from Delta Exchange to scan against...")
            from .scanner.rank_universe import rank_universe
            top_symbols = rank_universe(
                client, resolution=a.resolution, lookback_bars=a.lookback_bars or 100,
                adx_len=a.adx_len, trend_min=a.adx_trend_min, range_max=a.adx_range_max,
                min_turnover_usd=500_000, max_funding_pct=2.0, atr_min_pct=0.0, atr_max_pct=100.0,
                quote_symbol_suffix="USD", contract_types=["perpetual_future"],
                regime_bias="trend", top=a.top or 20, workers=4
            )
            symbols = [s.symbol for s in top_symbols]
            
        if not symbols:
            print("No symbols found to scan.", file=sys.stderr)
            return 2
            
        print(f"[scan] Running '{a.strategy}' against {len(symbols)} symbols @ {a.resolution}")
        
        table_rows = []
        for sym in symbols:
            try:
                bars = load_history(client, sym, a.resolution, start, end)
                if not bars:
                    table_rows.append([sym, "-", "-", "-", "-", "-", "✗ NO DATA"])
                    continue
                    
                cfg.symbol = sym
                strat = load_strategy(a.strategy, {})
                pf = run_backtest(bars, strat, cfg)
                s = summarize(pf)
                table_rows.append([
                    sym, f"{s['return_pct']:.2f}%", str(s['trades']),
                    f"{s['win_rate_pct']:.1f}%", f"{s['profit_factor']:.2f}",
                    f"{s['max_drawdown_pct']:.2f}%", "✓ OK"
                ])
            except Exception as e:
                table_rows.append([sym, "-", "-", "-", "-", "-", f"✗ ERROR: {e}"])
                
        def sort_key(row):
            try:
                if row[1] == "-": return -999999
                return float(row[1].replace("%", ""))
            except:
                return -999999
        table_rows.sort(key=sort_key, reverse=True)
                
        headers = ["Symbol", "Return %", "Trades", "Win Rate %", "Profit Factor", "Max DD %", "Status"]
        print("\\n" + render_box_table(headers, table_rows, title=f"STRATEGY SCANNER ({a.strategy} @ {a.resolution})") + "\\n")
        
    return 0

"""

code = code[:start_idx] + new_cmd_scan + code[end_idx:]

with open("delta_bt/cli.py", "w") as f:
    f.write(code)

print("Applied all fixes to cli.py")

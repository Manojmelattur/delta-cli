import sys

with open("delta_bt/cli.py", "r") as f:
    code = f.read()

def update_scan_parser():
    global code
    old_parser = """    # Market Scanner
    sc = sub.add_parser("scan", help="Scan and rank strategies against an asset")
    sc.add_argument("--symbol", required=True, help="Asset symbol (e.g. BTCUSD)")
    sc.add_argument("--resolution", default="1h")"""
    new_parser = """    # Market Scanner
    sc = sub.add_parser("scan", help="Scan and rank strategies against an asset, or scan an asset universe for a strategy")
    sc.add_argument("--symbol", default=None, help="Asset symbol (e.g. BTCUSD). Optional if --strategy is provided.")
    sc.add_argument("--strategy", default=None, help="Strategy to scan against the market universe. Optional if --symbol is provided.")
    sc.add_argument("--resolution", default="1h")"""
    if old_parser in code:
        code = code.replace(old_parser, new_parser)

def update_cmd_scan():
    global code
    
    start_idx = code.find("def cmd_scan(a) -> int:")
    if start_idx == -1:
        print("Could not find cmd_scan")
        return
        
    end_idx = code.find("def cmd_rank_universe(a) -> int:", start_idx)
    if end_idx == -1:
        print("Could not find end of cmd_scan")
        return

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
                
        # Sort by return_pct if it's a valid number
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
    code = code[:start_idx] + new_cmd_scan + "\n" + code[end_idx:]

update_scan_parser()
update_cmd_scan()

with open("delta_bt/cli.py", "w") as f:
    f.write(code)
print("Updated scan command in cli.py")

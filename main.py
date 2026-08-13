#!/usr/bin/env python3
"""
Delta Backtester Console — Standalone Interactive Terminal Application
Minimal, Clean & Colorful Terminal Interface
"""

import os
import sys
import subprocess

# ANSI Color Codes
C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"
C_GREEN   = "\033[1;32m"
C_CYAN    = "\033[1;36m"
C_YELLOW  = "\033[1;33m"
C_RED     = "\033[1;31m"
C_MAGENTA = "\033[1;35m"
C_BLUE    = "\033[1;34m"

def clear_screen():
    print("\033[2J\033[H", end="")

def print_banner():
    print(f"{C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C_RESET}")
    print(f"  {C_BOLD}{C_GREEN}⚡ DELTA EXCHANGE INDIA{C_RESET} {C_DIM}— Standalone Console Terminal{C_RESET}")
    print(f"{C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C_RESET}\n")

def run_cli_command(args_list):
    cmd = [sys.executable, "-m", "delta_bt"] + args_list
    print(f"\n{C_DIM}▶ Executing: {' '.join(cmd)}{C_RESET}\n")
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}Cancelled by user.{C_RESET}")
    input(f"\n{C_DIM}Press Enter to return to menu...{C_RESET}")

def select_strategy_interactive(default="supertrend_mom") -> str:
    """Interactive numbered strategy selector."""
    try:
        from delta_bt.core.registry import discover_strategies
        all_strats = sorted(list(discover_strategies().keys()))
    except Exception:
        all_strats = [
            "supertrend_mom", "ema_cross", "ema3", "rsi_mr", "bollinger",
            "price_action_pinbar", "price_action_engulfing", "smc_ob_fvg",
            "smc_liquidity_sweep", "fvg", "vwap", "grid", "macd"
        ]
    
    popular = [
        "supertrend_mom", "ema_cross", "ema3", "rsi_mr", "bollinger",
        "price_action_pinbar", "price_action_engulfing", "smc_ob_fvg",
        "smc_liquidity_sweep", "fvg", "vwap", "grid"
    ]
    # Ensure popular list is populated from discover_strategies if available
    popular_strats = [s for s in popular if s in all_strats] or all_strats[:12]
    
    print(f" {C_BOLD}Select Strategy:{C_RESET}")
    for idx, s in enumerate(popular_strats, 1):
        def_tag = f" {C_GREEN}(default){C_RESET}" if s == default else ""
        print(f"   {C_CYAN}{idx:>2}.{C_RESET} {s:<24}{def_tag}")
    print(f"   {C_CYAN} 0.{C_RESET} View All Strategies ({len(all_strats)}) / Type Custom Name\n")
    
    choice = input(f" {C_BOLD}Select number [1-{len(popular_strats)}] or press Enter for default [{default}]:{C_RESET} ").strip()
    if not choice:
        return default
    if choice.isdigit():
        val = int(choice)
        if 1 <= val <= len(popular_strats):
            return popular_strats[val - 1]
        elif val == 0:
            print("\n" + C_DIM + "Available Strategies:" + C_RESET)
            for idx, s in enumerate(all_strats, 1):
                print(f"  {idx:>2}. {s}")
            custom = input(f"\n Select number or type strategy name [{default}]: ").strip()
            if not custom:
                return default
            if custom.isdigit() and 1 <= int(custom) <= len(all_strats):
                return all_strats[int(custom) - 1]
            return custom
    return choice

def menu_backtest():
    while True:
        clear_screen()
        print_banner()
        print(f"{C_BOLD}{C_MAGENTA}📈 BACKTESTING ENGINE{C_RESET}\n")
        print(f"  {C_CYAN}1.{C_RESET} Run Strategy Backtest")
        print(f"  {C_CYAN}2.{C_RESET} 🧹 Clean Old Backtest & Scan Reports (Frees Disk Space)")
        print(f"  {C_CYAN}3.{C_RESET} Back to Main Menu\n")
        
        c = input(f" {C_BOLD}Select [1-3]:{C_RESET} ").strip()
        
        if c == "1":
            strategy = select_strategy_interactive(default="supertrend_mom")
            symbol   = input(f" {C_CYAN}Symbol{C_RESET}   [BTCUSD]: ").strip() or "BTCUSD"
            tf       = input(f" {C_CYAN}Timeframe{C_RESET}[15m]: ").strip() or "15m"
            days     = input(f" {C_CYAN}Days{C_RESET}     [60]: ").strip() or "60"
            run_cli_command(["backtest", "--strategy", strategy, "--symbol", symbol, "--timeframe", tf, "--days", days])
        
        elif c == "2":
            import glob
            import shutil
            import os
            print(f"\n {C_DIM}Scanning for old reports...{C_RESET}")
            paths = glob.glob("reports/backtest_*") + glob.glob("reports/scan_*")
            if not paths:
                print(f" {C_GREEN}No old reports found. Your disk is clean!{C_RESET}")
            else:
                for p in paths:
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p)
                        else:
                            os.remove(p)
                    except Exception as e:
                        pass
                print(f" {C_GREEN}Successfully deleted {len(paths)} old report folders!{C_RESET}")
            input(f"\n{C_DIM}Press Enter to return...{C_RESET}")
            
        elif c == "3":
            break

def menu_scheduled_trade():
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_CYAN}⏱️ SCHEDULED TRADING & AUTOMATED EXECUTION{C_RESET}\n")
    print(f"  {C_CYAN}1.{C_RESET} Deploy Recurring Strategy Bot (Scheduled Execution)")
    print(f"  {C_CYAN}2.{C_RESET} One-Shot Strategy Evaluation & Immediate Order (`trade`)")
    print(f"  {C_CYAN}3.{C_RESET} Start Foreground Watcher Loop (`watch`)")
    print(f"  {C_CYAN}4.{C_RESET} 🚀 Launch Headless Background Watcher Daemon (Survives Terminal Exit)")
    print(f"  {C_CYAN}5.{C_RESET} Schedule New Background Task (`tasks add`)")
    print(f"  {C_CYAN}6.{C_RESET} List Active Scheduled Deployments")
    print(f"  {C_CYAN}7.{C_RESET} Back to Main Menu\n")
    
    c = input(f" {C_BOLD}Select [1-7]:{C_RESET} ").strip()
    if c == "1":
        name = input(f" {C_CYAN}Bot Name{C_RESET} [Scheduled Bot]: ").strip() or "Scheduled Bot"
        venue = input(f" {C_CYAN}Venue (testnet/live){C_RESET} [testnet]: ").strip() or "testnet"
        strategy = select_strategy_interactive(default="supertrend_mom")
        symbol = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
        tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
        size = input(f" {C_CYAN}Lot Size{C_RESET} [1]: ").strip() or "1"
        interval = input(f" {C_CYAN}Schedule Interval (sec){C_RESET} [300]: ").strip() or "300"
        
        args = ["deployments", "add", "--name", name, "--venue", venue, "--strategy", strategy,
                "--symbol", symbol, "--resolution", tf, "--lot", size, "--interval", interval]
        if venue == "live": args.append("--i-understand-live")
        run_cli_command(args)
    elif c == "2":
        venue = input(f" {C_CYAN}Venue (testnet/live){C_RESET} [testnet]: ").strip() or "testnet"
        strategy = select_strategy_interactive(default="smc_ob_fvg")
        symbol = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
        tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
        size = input(f" {C_CYAN}Lot Size{C_RESET} [1]: ").strip() or "1"
        
        args = ["trade", "--venue", venue, "--strategy", strategy, "--symbol", symbol, "--resolution", tf, "--lot", size]
        if venue == "live": args.append("--i-understand-live")
        run_cli_command(args)
    elif c == "3":
        interval = input(f" {C_CYAN}Watcher Loop Tick Interval (sec){C_RESET} [15]: ").strip() or "15"
        run_cli_command(["watch", "--interval", interval])
    elif c == "4":
        interval = input(f" {C_CYAN}Watcher Loop Tick Interval (sec){C_RESET} [15]: ").strip() or "15"
        cmd = f"nohup {sys.executable} -m delta_bt watch --interval {interval} > watcher.log 2>&1 &"
        subprocess.run(cmd, shell=True)
        print(f"\n{C_GREEN}🚀 Headless Watcher Daemon Launched in Background!{C_RESET}")
        print(f" {C_DIM}• Log output file: watcher.log{C_RESET}")
        print(f" {C_DIM}• Safe to exit or close terminal — bots will keep trading 24/7 continuous!{C_RESET}")
        input(f"\n{C_DIM}Press Enter to return to menu...{C_RESET}")
    elif c == "5":
        name = input(f" {C_CYAN}Task Name{C_RESET} [Risk Guard]: ").strip() or "Risk Guard"
        script = input(f" {C_CYAN}Script in delta_bt/tasks/{C_RESET} [emergency_monitor.py]: ").strip() or "emergency_monitor.py"
        interval = input(f" {C_CYAN}Execution Interval (sec){C_RESET} [300]: ").strip() or "300"
        run_cli_command(["tasks", "add", "--name", name, "--script", script, "--interval", interval])
    elif c == "6":
        run_cli_command(["deployments", "list"])

def menu_deployments():
    import json as _dj

    def _load_bots():
        from delta_bt.deployments import list_deployments
        return [dict(r) for r in list_deployments()]

    def _pick_bot(bots, prompt="Bot ID or list #") -> dict | None:
        raw = input(f" {C_CYAN}{prompt}:{C_RESET} ").strip()
        if not raw:
            return None
        if raw.isdigit():
            val = int(raw)
            by_id = next((b for b in bots if b["id"] == val), None)
            if by_id:
                return by_id
            if 1 <= val <= len(bots):
                return bots[val - 1]
        return None

    def _show_bot_detail(b: dict) -> None:
        sc  = C_GREEN if b["status"] == "running" else (C_YELLOW if b["status"] == "paused" else C_DIM)
        pnl = b.get("realized_pnl", 0) or 0
        pc  = C_GREEN if pnl >= 0 else C_RED
        print(f"\n {C_BOLD}Bot #{b['id']} — {b['name']}{C_RESET}")
        print(f"   Status    : {sc}{b['status']}{C_RESET}")
        print(f"   Venue     : {C_CYAN}{b['venue']}{C_RESET}")
        print(f"   Strategy  : {b['strategy']}")
        print(f"   Symbol    : {b['symbol']}  /  TF: {b['resolution']}")
        print(f"   Lot Size  : {b['size']}")
        print(f"   SL / TP   : {b.get('sl_pct',0)}% / {b.get('tp_pct',0)}%")
        print(f"   Trail     : {b.get('trail_pct',0)}%  (activates at +{b.get('trail_activate_pct',0)}%)")
        print(f"   Breakeven : +{b.get('breakeven_after_pct',0)}%")
        print(f"   Leverage  : {b.get('leverage',1)}x")
        print(f"   Interval  : {b.get('interval_sec',300)}s")
        print(f"   Realized  : {pc}${pnl:+.4f}{C_RESET}")
        print(f"   Last Sig  : {b.get('last_signal') or '—'}")
        try:
            params = _dj.loads(b.get("params_json") or "{}")
            if params:
                print(f"   Params:")
                for k, v in params.items():
                    print(f"     {C_DIM}{k:<26}{C_RESET} {C_CYAN}{v}{C_RESET}")
        except Exception:
            pass
        print()

    _TFS    = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"]
    _VENUES = ["paper", "testnet", "paper_live", "live"]
    _STATUS = ["running", "paused", "stopped"]

    while True:
        clear_screen()
        print_banner()
        print(f"{C_BOLD}{C_GREEN}🤖 BOT MANAGER{C_RESET}\n")

        bots = _load_bots()

        if bots:
            print(f" {'#':<4} {'ID':<5} {'Status':<9} {'Venue':<11} {'Strategy':<18} {'Symbol':<12} {'TF':<5} {'Lot':<7} {'SL%':<6} {'TP%':<6} {'PnL $'}")
            print(f" {C_DIM}{'─'*100}{C_RESET}")
            for idx, b in enumerate(bots, 1):
                sc  = C_GREEN if b["status"] == "running" else (C_YELLOW if b["status"] == "paused" else C_DIM)
                pnl = b.get("realized_pnl", 0) or 0
                pc  = C_GREEN if pnl >= 0 else C_RED
                
                strat = str(b.get('strategy', ''))[:18]
                sym = str(b.get('symbol', ''))[:12]
                
                print(
                    f" {C_DIM}{idx:<4}{C_RESET} {b['id']:<5}"
                    f" {sc}{b['status']:<9}{C_RESET}"
                    f" {b['venue']:<11} {strat:<18} {sym:<12}"
                    f" {b['resolution']:<5} {b['size']:<7}"
                    f" {b.get('sl_pct',0):<6} {b.get('tp_pct',0):<6}"
                    f" {pc}{pnl:+.2f}{C_RESET}"
                )
        else:
            print(f"  {C_DIM}(no bots deployed){C_RESET}")

        print(f"""
  {C_CYAN}1.{C_RESET} 🔍 View Bot Detail
  {C_CYAN}2.{C_RESET} ➕ Deploy New Bot
  {C_CYAN}3.{C_RESET} ⏸  Pause Bot
  {C_CYAN}4.{C_RESET} ▶  Resume Bot
  {C_CYAN}5.{C_RESET} 🛑 Stop Bot
  {C_CYAN}6.{C_RESET} 🗑 Delete Bot
  {C_CYAN}7.{C_RESET} 📜 View Bot Events
  {C_CYAN}8.{C_RESET} ⏸️  Pause ALL Bots
  {C_CYAN}9.{C_RESET} ▶️  Resume ALL Bots
  {C_CYAN}10.{C_RESET} 🛑 Stop ALL Bots
  {C_CYAN}11.{C_RESET} ↩ Back
""")

        c = input(f" {C_BOLD}Select [1-11]:{C_RESET} ").strip()

        if c == "1":
            b = _pick_bot(bots)
            if b:
                clear_screen(); print_banner(); _show_bot_detail(b)
                input(f"{C_DIM}Press Enter to return…{C_RESET}")

        elif c == "2":
            name = input(f" {C_CYAN}◆ Bot Name{C_RESET} [CLI Bot]: ").strip() or "CLI Bot"
            print(f"\n {C_CYAN}◆ Venue{C_RESET}")
            for i, v in enumerate(_VENUES, 1): print(f"     {i}. {v}")
            vr = input(f"   Select [1-4] [testnet]: ").strip()
            venue = _VENUES[int(vr)-1] if vr.isdigit() and 1 <= int(vr) <= 4 else "testnet"
            strategy = select_strategy_interactive(default="supertrend_mom")
            symbol   = input(f" {C_CYAN}◆ Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
            print(f"\n {C_CYAN}◆ Timeframe{C_RESET}")
            for i, t in enumerate(_TFS, 1): print(f"     {i}. {t}")
            tr = input(f"   Select [1-{len(_TFS)}] [15m]: ").strip()
            tf = _TFS[int(tr)-1] if tr.isdigit() and 1 <= int(tr) <= len(_TFS) else "15m"
            size = input(f" {C_CYAN}◆ Lot Size{C_RESET} [1]: ").strip() or "1"
            sl   = input(f" {C_CYAN}◆ Stop-Loss %{C_RESET} [1.5]: ").strip() or "1.5"
            tp   = input(f" {C_CYAN}◆ Take-Profit %{C_RESET} [3.0]: ").strip() or "3.0"
            trail= input(f" {C_CYAN}◆ Trailing Stop %{C_RESET} [0]: ").strip() or "0"

            # --- Advanced Risk JSON Prompt ---
            default_advanced_json = _dj.dumps({
                "use_kelly_sizer": True,
                "use_maker_limit": True,
                "use_atr_risk": True,
                "risk_type": "percentage",
                "multiple_tp": [{"pct": 1.0, "qty_pct": 50}, {"pct": 2.0, "qty_pct": 50}]
            }, indent=2)
            params_str = ""
            if input(f"\n {C_CYAN}◆ Configure Advanced Risk (Kelly/Maker/ATR/Multiple-TP) as JSON? (Opens editor) [y/N]:{C_RESET} ").strip().lower() in ("y", "yes"):
                import click
                edited = click.edit(default_advanced_json, extension=".json")
                if edited is not None:
                    try:
                        _dj.loads(edited)
                        params_str = edited
                        print(f"   {C_GREEN}JSON updated.{C_RESET}")
                    except Exception:
                        print(f"   {C_YELLOW}Invalid JSON — skipping params{C_RESET}")
                else:
                    print(f"   {C_YELLOW}Editor aborted — skipping params{C_RESET}")

            args = [
                "deployments", "add",
                "--name", name, "--venue", venue, "--strategy", strategy,
                "--symbol", symbol, "--resolution", tf, "--lot", size,
                "--sl-pct", sl, "--tp-pct", tp, "--trail-pct", trail,
            ]
            if params_str:
                args += ["--params", params_str]
            if venue == "live": args.append("--i-understand-live")
            run_cli_command(args)

        elif c in ("3", "4", "5"):
            action = {"3": "pause", "4": "resume", "5": "stop"}[c]
            b = _pick_bot(bots, f"Bot # or ID to {action}")
            if b:
                run_cli_command(["deployments", action, "--id", str(b["id"])])

        elif c == "6":
            b = _pick_bot(bots, "Bot # or ID to delete")
            if b:
                if b.get("status", "").lower() != "paused":
                    print(f" {C_RED}Only paused bots can be deleted.{C_RESET}")
                    input(f"{C_DIM}Press Enter...{C_RESET}")
                else:
                    if input(f" {C_RED}DELETE bot '{b['name']}'? [y/N]:{C_RESET} ").strip().lower() == "y":
                        run_cli_command(["deployments", "delete", "--id", str(b["id"])])

        elif c == "7":
            b = _pick_bot(bots, "Bot # or ID for events")
            if b:
                run_cli_command(["bot-show", "--id", str(b["id"])])

        elif c == "8":
            if input(f" {C_YELLOW}Pause ALL bots? [y/N]:{C_RESET} ").strip().lower() == "y":
                run_cli_command(["deployments", "pause-all"])
        elif c == "9":
            if input(f" {C_GREEN}Resume ALL bots? [y/N]:{C_RESET} ").strip().lower() == "y":
                run_cli_command(["deployments", "resume-all"])
        elif c == "10":
            if input(f" {C_RED}STOP ALL bots? [y/N]:{C_RESET} ").strip().lower() == "y":
                run_cli_command(["deployments", "stop-all"])
        elif c == "11":
            break


def menu_scanner():
    while True:
        clear_screen()
        print_banner()
        print(f"{C_BOLD}{C_YELLOW}🔍 MARKET SCANNER & RANKING{C_RESET}\n")
        print(f"  {C_CYAN}1.{C_RESET} Scan Parameter Grid for Symbol (Find best params)")
        print(f"  {C_CYAN}2.{C_RESET} Rank Top Market Gainers / Volume")
        print(f"  {C_CYAN}3.{C_RESET} Sweep All Strategies (Backtest 16+ strategies on a symbol)")
        print(f"  {C_CYAN}4.{C_RESET} Auto-Scan & Auto-Deploy (Scan market, deploy top bots)")
        print(f"  {C_CYAN}5.{C_RESET} Deploy Advanced Custom Hunter/Scanner")
        print(f"  {C_CYAN}6.{C_RESET} Back to Main Menu\n")
        
        c = input(f" {C_BOLD}Select [1-6]:{C_RESET} ").strip()
        
        if c == "1":
            sym = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
            tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
            run_cli_command(["scan", "--symbol", sym, "--timeframe", tf, "--top", "10"])
            
        elif c == "2":
            top = input(f" {C_CYAN}Top N Coins{C_RESET} [15]: ").strip() or "15"
            run_cli_command(["rank-universe", "--top", top])
            
        elif c == "3":
            sym = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
            tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
            days = input(f" {C_CYAN}Lookback Days{C_RESET} [30]: ").strip() or "30"
            run_cli_command(["sweep", "--symbol", sym, "--resolution", tf, "--days", days])
            
        elif c == "4":
            print(f"\n {C_DIM}This will scan the top coins, rank all strategies by PnL+WinRate, and deploy bots for the best setups.{C_RESET}")
            print(f" {C_DIM}If you provide a symbol, it will skip the market scan and only sweep strategies for that symbol.{C_RESET}")
            
            sym = input(f" {C_CYAN}Optional Symbol (leave blank to scan market){C_RESET}: ").strip()
            
            top = "1"
            if not sym:
                top = input(f" {C_CYAN}Top N coins to scan{C_RESET} [5]: ").strip() or "5"
                
            venue = input(f" {C_CYAN}Target Venue (paper/testnet/live){C_RESET} [paper]: ").strip() or "paper"
            tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
            sl = input(f" {C_CYAN}Stop Loss %{C_RESET} [1.5]: ").strip() or "1.5"
            tp = input(f" {C_CYAN}Take Profit %{C_RESET} [3.0]: ").strip() or "3.0"
            trail = input(f" {C_CYAN}Trailing Stop %{C_RESET} [0]: ").strip() or "0"
            days = input(f" {C_CYAN}Lookback Days{C_RESET} [7]: ").strip() or "7"
            
            args = ["auto-deploy", "--venue", venue, "--timeframe", tf,
                    "--sl-pct", sl, "--tp-pct", tp, "--trail-pct", trail, "--days", days]
            
            if sym:
                args.extend(["--symbol", sym])
            else:
                args.extend(["--top", top])
            
            if venue == "live":
                args.append("--live")
            else:
                args.append("--testnet")
                
            run_cli_command(args)
            
        elif c == "5":
            import json as _sj
            from delta_bt.task_registry import get_catalog
            cat = get_catalog()
            
            # Filter to Hunters, Scanners, and Arbitrage
            scanners = [t for t in cat if t["category"] in ("Hunters & Snipers", "Market Scanners", "Yield & Arbitrage")]
            if not scanners:
                print(f" {C_YELLOW}No custom scanners found.{C_RESET}")
                input(f"{C_DIM}Press Enter...{C_RESET}")
                continue
                
            clear_screen()
            print(f"\n{C_BOLD}{C_GREEN}🏹 ADVANCED HUNTERS & SCANNERS{C_RESET}\n")
            for idx, t in enumerate(scanners, 1):
                print(f"  {C_CYAN}{idx}.{C_RESET} {C_BOLD}{t['name']}{C_RESET} {C_DIM}({t['script']}){C_RESET}")
                print(f"     {t['desc']}")
                print()
                
            sel = input(f" Select [1-{len(scanners)}] or Enter to cancel: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(scanners):
                t = scanners[int(sel)-1]
                print(f"\n {C_BOLD}Deploying: {t['name']}{C_RESET}")
                
                name = input(
                    f" {C_CYAN}◆ Task Name{C_RESET} [{t['name']}]: "
                ).strip() or t["name"]
                
                # Use _prompt_field wizard for default params
                final_params = {}
                def_params = t.get("params", {})
                for k, v in def_params.items():
                    final_params[k] = _prompt_field(k, v)
                    
                interval = input(f" {C_CYAN}Interval (seconds){C_RESET} [{t.get('default_interval', 3600)}]: ").strip()
                if not interval.isdigit():
                    interval = str(t.get('default_interval', 3600))
                    
                p_str = _sj.dumps(final_params)
                print(f"\n {C_DIM}Deploying as background task...{C_RESET}")
                run_cli_command([
                    "tasks", "add", 
                    "--name", name,
                    "--script", t["script"], 
                    "--interval", interval, 
                    "--desc", t.get("desc", ""),
                    "--params", p_str
                ])
            
        elif c == "6":
            break


# ─────────────────────────────────────────────────────────────────────────────
# Common parameter definitions for field-by-field prompting
# ─────────────────────────────────────────────────────────────────────────────

# Maps param key → (label, type, choices/None, hint)
_PARAM_META = {
    "venue": (
        "Venue",
        "choice",
        ["paper", "testnet", "paper_live", "live"],
        "Where trades execute",
    ),
    "base_lot_size": ("Lot Size (contracts)", "int",   None, "Minimum 1"),
    "symbol":        ("Symbol",               "str",   None, "e.g. BTCUSD"),
    "symbols":       ("Symbols (CSV)",        "str",   None, "e.g. BTCUSD,ETHUSD"),
    "strategy":      ("Strategy",             "strat", None, ""),
    "timeframe":     ("Timeframe",            "choice",["1m","5m","15m","30m","1h","4h","1d"], ""),
    "resolutions":   ("Resolutions (CSV)",    "str",   None, "e.g. 15m,1h"),
    "sl_pct":        ("Stop-Loss %",          "float", None, "e.g. 1.5"),
    "tp_pct":        ("Take-Profit %",        "float", None, "e.g. 3.0  (0 = disabled)"),
    "trail_pct":     ("Trailing Stop %",      "float", None, "e.g. 1.0  (0 = disabled)"),
    "trail_activate_pct": ("Trail Activates After %", "float", None, "e.g. 1.0"),
    "breakeven_after_pct":("Breakeven After % profit","float", None, "e.g. 1.0  (0 = disabled)"),
    "leverage":      ("Leverage",             "float", None, "e.g. 1.0"),
    "top_n_symbols": ("Top N Symbols",        "int",   None, "Number of top symbols to scan"),
    "max_trades":    ("Max Simultaneous Trades","int", None, ""),
    "lookback_days": ("Lookback Days",        "int",   None, "Signal window in days"),
    "profit_lookback_days":("Profit Filter Days","int",None, "30-day backtest window"),
    "min_win_rate":  ("Min Win Rate",         "float", None, "0.0–1.0, e.g. 0.45"),
    "min_pnl":       ("Min PnL Filter",       "float", None, "Minimum 30d PnL"),
    "workers":       ("Parallel Workers",     "int",   None, "Thread count for scanning"),
    "auto_deploy":   ("Auto Deploy",          "bool",  None, ""),
    "dry_run":       ("Dry Run (no real trades)","bool",None,""),
    "telegram_notify":("Telegram Notify",    "bool",  None, ""),
    "max_margin_utilization":("Max Margin Utilization","float",None,"0.0–1.0"),
    "max_leverage_cap":      ("Max Leverage Cap",     "float",None,""),
    "max_total_exposure_usd":("Max Exposure USD",     "float",None,""),
    "max_drawdown_limit_pct":("Max Drawdown Limit %", "float",None,""),
    "min_funding_annualized_pct":("Min Funding APY %","float",None,""),
    "flash_crash_threshold_pct": ("Flash Crash Threshold %","float",None,""),
    "pause_duration_min":        ("Pause Duration (min)","int",None,""),
    "risk_per_trade_pct":        ("Risk Per Trade %","float",None,""),
    "max_inactive_hours":        ("Max Inactive Hours","int", None,""),
    "days":          ("Days",                 "int",   None, ""),
    "z_threshold":   ("Z-Score Threshold",    "float", None, ""),
    "min_apy_pct":   ("Min APY %",            "float", None, ""),
}

_VENUES = ["paper", "testnet", "paper_live", "live"]


def _prompt_field(key: str, current_val) -> object:
    """Prompt the user for a single parameter field with type-aware UX."""
    meta = _PARAM_META.get(key)
    if meta:
        label, kind, choices, hint = meta
    else:
        label = key.replace("_", " ").title()
        kind  = "str"
        choices = None
        hint  = ""

    hint_str  = f"  {C_DIM}({hint}){C_RESET}" if hint else ""
    cur_str   = str(current_val) if current_val is not None else ""

    # ── Strategy: use interactive selector ────────────────────────────────────
    if kind == "strat":
        print(f"\n {C_CYAN}◆ {label}{C_RESET}{hint_str}")
        return select_strategy_interactive(default=cur_str or "ema3")

    # ── Choice list ───────────────────────────────────────────────────────────
    if kind == "choice" and choices:
        print(f"\n {C_CYAN}◆ {label}{C_RESET}{hint_str}")
        for i, c in enumerate(choices, 1):
            tag = f" {C_GREEN}← current{C_RESET}" if str(current_val) == c else ""
            print(f"     {C_DIM}{i}.{C_RESET} {c}{tag}")
        raw = input(
            f"   {C_BOLD}Select [1-{len(choices)}] or type value [{cur_str}]:{C_RESET} "
        ).strip()
        if not raw:
            return current_val
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1]
        return raw

    # ── Bool ──────────────────────────────────────────────────────────────────
    if kind == "bool":
        cur_yn = "y" if current_val else "n"
        raw = input(
            f" {C_CYAN}◆ {label}{C_RESET}{hint_str}"
            f" [{'Y/n' if current_val else 'y/N'}]: "
        ).strip().lower()
        if not raw:
            return current_val
        return raw in ("y", "yes", "true", "1")

    # ── Int ───────────────────────────────────────────────────────────────────
    if kind == "int":
        raw = input(
            f" {C_CYAN}◆ {label}{C_RESET}{hint_str} [{cur_str}]: "
        ).strip()
        if not raw:
            return current_val
        try:
            return int(raw)
        except ValueError:
            print(f"   {C_YELLOW}Invalid integer — keeping {cur_str}{C_RESET}")
            return current_val

    # ── Float ─────────────────────────────────────────────────────────────────
    if kind == "float":
        raw = input(
            f" {C_CYAN}◆ {label}{C_RESET}{hint_str} [{cur_str}]: "
        ).strip()
        if not raw:
            return current_val
        try:
            return float(raw)
        except ValueError:
            print(f"   {C_YELLOW}Invalid number — keeping {cur_str}{C_RESET}")
            return current_val

    # ── Default: string ───────────────────────────────────────────────────────
    raw = input(
        f" {C_CYAN}◆ {label}{C_RESET}{hint_str} [{cur_str}]: "
    ).strip()
    return raw if raw else current_val


def _prompt_task_params(task_params: dict, schema_defaults: dict) -> dict:
    """Walk through ALL params field-by-field.

    Order:
      1. Known params that exist in the current params dict OR in schema_defaults,
         shown in a sensible order (common ones first).
      2. Any remaining schema_defaults keys not yet shown.
      3. Offer to add an ad-hoc custom param.
    """
    import json as _j

    # Build the working param set: start from schema defaults, overlay stored params
    merged = dict(schema_defaults)
    merged.update(task_params)

    # Preferred display order for common params
    _COMMON_ORDER = [
        "venue", "base_lot_size", "symbol", "symbols", "strategy",
        "timeframe", "resolutions", "sl_pct", "tp_pct", "trail_pct",
        "trail_activate_pct", "breakeven_after_pct", "leverage",
        "top_n_symbols", "max_trades", "lookback_days",
        "profit_lookback_days", "min_win_rate", "min_pnl",
        "auto_deploy", "dry_run", "workers",
    ]

    all_keys = list(_COMMON_ORDER)
    for k in merged:
        if k not in all_keys:
            all_keys.append(k)

    # Only prompt for keys that actually exist in the merged params
    keys_to_show = [k for k in all_keys if k in merged]

    updated = {}
    for key in keys_to_show:
        updated[key] = _prompt_field(key, merged[key])

    # Offer to add a custom/extra param
    print(f"\n {C_DIM}─ Add custom param? (e.g. z_threshold){C_RESET}")
    while True:
        extra_key = input(
            f" {C_DIM}Custom param key (press Enter to skip):{C_RESET} "
        ).strip()
        if not extra_key:
            break
        extra_val = input(f"   Value for '{extra_key}': ").strip()
        # Try to parse as number or bool first
        for fn in (int, float):
            try:
                extra_val = fn(extra_val); break
            except (ValueError, TypeError):
                pass
        if isinstance(extra_val, str) and extra_val.lower() in ("true", "false"):
            extra_val = extra_val.lower() == "true"
        updated[extra_key] = extra_val

    return updated


def _show_task_detail(t: dict) -> None:
    """Print a detailed single-task info block."""
    import json as _j
    status_col = C_GREEN if t["status"] == "running" else C_YELLOW
    print(f"\n {C_BOLD}Task #{t['id']} — {t['name']}{C_RESET}")
    print(f"   Script   : {C_CYAN}{t['script_name']}{C_RESET}")
    print(f"   Status   : {status_col}{t['status']}{C_RESET}")
    print(f"   Interval : {t['interval_sec']}s  ({t['interval_sec']//60}m {t['interval_sec']%60}s)")
    print(f"   Last Run : {t.get('last_run_at') or '—'}")
    try:
        params = _j.loads(t.get("params_json") or "{}")
        if params:
            print(f"   Params:")
            for k, v in params.items():
                print(f"     {C_DIM}{k:<28}{C_RESET} {C_CYAN}{v}{C_RESET}")
        else:
            print(f"   Params   : (none)")
    except Exception:
        print(f"   Params   : {t.get('params_json')}")
    last_report = t.get("last_report")
    if last_report:
        snippet = last_report[:160].replace("\n", " ")
        print(f"   Last Log : {C_DIM}{snippet}…{C_RESET}")
    print()


def menu_tasks():
    import json as _j

    def _load_tasks():
        from delta_bt.store.db import list_background_tasks
        return [dict(r) for r in list_background_tasks()]

    def _pick_task(tasks, prompt="Task ID or list number") -> dict | None:
        """Let user type a task ID or list position number."""
        raw = input(f" {C_CYAN}{prompt}:{C_RESET} ").strip()
        if not raw:
            return None
        if raw.isdigit():
            val = int(raw)
            # Try as direct ID first
            by_id = next((t for t in tasks if t["id"] == val), None)
            if by_id:
                return by_id
            # Then as 1-based list index
            if 1 <= val <= len(tasks):
                return tasks[val - 1]
        return None

    while True:
        clear_screen()
        print_banner()
        print(f"{C_BOLD}{C_BLUE}⚙️  BACKGROUND TASK MANAGER{C_RESET}\n")

        tasks = _load_tasks()

        # ── Live task list ────────────────────────────────────────────────────
        if tasks:
            print(f" {'#':<4} {'ID':<5} {'Status':<9} {'Interval':<10} {'Script':<30} Name")
            print(f" {C_DIM}{'─'*85}{C_RESET}")
            for idx, t in enumerate(tasks, 1):
                sc = C_GREEN if t["status"] == "running" else C_YELLOW
                print(
                    f" {C_DIM}{idx:<4}{C_RESET}"
                    f" {t['id']:<5}"
                    f" {sc}{t['status']:<9}{C_RESET}"
                    f" {t['interval_sec']:<10}"
                    f" {C_CYAN}{t['script_name']:<30}{C_RESET}"
                    f" {t['name']}"
                )
        else:
            print(f"  {C_DIM}(no tasks registered){C_RESET}")

        print(f"""
  {C_CYAN}1.{C_RESET} 📋 View Full Task Catalog
  {C_CYAN}2.{C_RESET} 🔍 View Task Detail + Params
  {C_CYAN}3.{C_RESET} 📜 View Task Logs
  {C_CYAN}4.{C_RESET} ▶  Run Task Once Now
  {C_CYAN}5.{C_RESET} ⏸  Pause Task
  {C_CYAN}6.{C_RESET} ▶  Resume Task
  {C_CYAN}7.{C_RESET} ➕ Schedule New Task  (field-by-field wizard)
  {C_CYAN}8.{C_RESET} ✏️  Edit Task  (name / interval / status / venue / lot size / all params)
  {C_CYAN}9.{C_RESET} ⏸️  Pause ALL Tasks
  {C_CYAN}10.{C_RESET} ▶  Resume ALL Tasks
  {C_CYAN}11.{C_RESET} 🗑  Remove Task
  {C_CYAN}12.{C_RESET} ← Back\n""")

        c = input(f" {C_BOLD}Select [1-12]:{C_RESET} ").strip()

        # ── 1. Catalog ────────────────────────────────────────────────────────
        if c == "1":
            run_cli_command(["tasks", "catalog"])

        # ── 2. Detail view ────────────────────────────────────────────────────
        elif c == "2":
            t = _pick_task(tasks, "Task # or ID to view")
            if t:
                clear_screen()
                print_banner()
                _show_task_detail(t)
                input(f"{C_DIM}Press Enter to return…{C_RESET}")

        # ── 3. Logs ───────────────────────────────────────────────────────────
        elif c == "3":
            t = _pick_task(tasks, "Task # or ID for logs")
            if t:
                run_cli_command(["tasks", "logs", "--id", str(t["id"])])

        # ── 4. Run now ────────────────────────────────────────────────────────
        elif c == "4":
            t = _pick_task(tasks, "Task # or ID to run now")
            if t:
                run_cli_command(["tasks", "run-now", "--id", str(t["id"])])

        # ── 5. Pause ──────────────────────────────────────────────────────────
        elif c == "5":
            t = _pick_task(tasks, "Task # or ID to pause")
            if t:
                run_cli_command(["tasks", "pause", "--id", str(t["id"])])

        # ── 6. Resume ─────────────────────────────────────────────────────────
        elif c == "6":
            t = _pick_task(tasks, "Task # or ID to resume")
            if t:
                run_cli_command(["tasks", "resume", "--id", str(t["id"])])

        # ── 7. Schedule New Task — full wizard ────────────────────────────────
        elif c == "7":
            from delta_bt.task_registry import get_catalog, get_task_metadata
            catalog = get_catalog()

            clear_screen()
            print_banner()
            print(f"{C_BOLD}📋 SELECT TASK FROM CATALOG{C_RESET}\n")
            for idx, item in enumerate(catalog, 1):
                print(
                    f"  {C_CYAN}{idx:>3}.{C_RESET}  {item['script']:<35}"
                    f" {C_DIM}{item['name']}{C_RESET}"
                )
            print(f"  {C_CYAN}  0.{C_RESET}  Type custom script name\n")

            sel_raw = input(
                f" {C_BOLD}Select [1-{len(catalog)}] or Enter for #1:{C_RESET} "
            ).strip()

            selected = catalog[0]
            if sel_raw.isdigit():
                v = int(sel_raw)
                if 1 <= v <= len(catalog):
                    selected = catalog[v - 1]
                elif v == 0:
                    cname = input(f" {C_CYAN}Script filename (e.g. daily_report.py):{C_RESET} ").strip()
                    if cname:
                        selected = get_task_metadata(cname)
            elif sel_raw:
                selected = get_task_metadata(sel_raw)

            clear_screen()
            print_banner()
            print(f"{C_BOLD}➕ NEW TASK — {selected['name']}{C_RESET}")
            print(f"   {C_DIM}{selected['desc']}{C_RESET}\n")

            # ── Basic fields ─────────────────────────────────────────────────
            name = input(
                f" {C_CYAN}◆ Task Name{C_RESET} [{selected['name']}]: "
            ).strip() or selected["name"]

            interval_raw = input(
                f" {C_CYAN}◆ Interval (sec){C_RESET} [{selected['default_interval']}]: "
            ).strip()
            interval = int(interval_raw) if interval_raw.isdigit() else selected["default_interval"]

            # ── Param wizard ─────────────────────────────────────────────────
            schema = selected.get("params", {})
            if schema:
                print(f"\n {C_BOLD}─── Task Parameters ───────────────────────────────{C_RESET}")
                print(f" {C_DIM}Press Enter to accept the default value shown in [ ]{C_RESET}\n")
                final_params = _prompt_task_params({}, schema)
            else:
                final_params = {}

            params_json = _j.dumps(final_params)
            print(f"\n {C_DIM}▶ Params: {params_json}{C_RESET}")

            confirm = input(
                f"\n {C_GREEN}Create task '{name}'? [Y/n]:{C_RESET} "
            ).strip().lower()
            if confirm in ("", "y", "yes"):
                run_cli_command([
                    "tasks", "add",
                    "--name",     name,
                    "--script",   selected["script"],
                    "--interval", str(interval),
                    "--desc",     selected.get("desc", "")[:120],
                    "--params",   params_json,
                ])

        # ── 8. Edit Task — full detail editor ─────────────────────────────────
        elif c == "8":
            t = _pick_task(tasks, "Task # or ID to edit")
            if not t:
                continue

            clear_screen()
            print_banner()
            _show_task_detail(t)
            print(f"{C_BOLD}✏️  EDITING TASK #{t['id']} — {t['name']}{C_RESET}\n")
            print(f" {C_DIM}Press Enter on any field to keep the current value.{C_RESET}\n")

            # ── Name ──────────────────────────────────────────────────────────
            new_name = input(
                f" {C_CYAN}◆ Name{C_RESET} [{t['name']}]: "
            ).strip() or None

            # ── Interval ─────────────────────────────────────────────────────
            int_raw = input(
                f" {C_CYAN}◆ Interval (sec){C_RESET} [{t['interval_sec']}]: "
            ).strip()
            new_interval = int(int_raw) if int_raw.isdigit() else None

            # ── Status ────────────────────────────────────────────────────────
            sc = t["status"]
            print(f"\n {C_CYAN}◆ Status{C_RESET}")
            print(f"     {C_DIM}1.{C_RESET} running  {'← current' if sc=='running' else ''}")
            print(f"     {C_DIM}2.{C_RESET} paused   {'← current' if sc=='paused'  else ''}")
            st_raw = input(f"   Select [1/2, Enter = keep]:{C_RESET} ").strip()
            new_status = None
            if st_raw == "1":   new_status = "running"
            elif st_raw == "2": new_status = "paused"

            # ── Params ────────────────────────────────────────────────────────
            try:
                current_params = _j.loads(t.get("params_json") or "{}")
            except Exception:
                current_params = {}

            from delta_bt.task_registry import get_task_metadata
            registry_entry = get_task_metadata(t["script_name"])
            schema_defaults = registry_entry.get("params", {})

            edit_params = input(
                f"\n {C_CYAN}◆ Edit task parameters? [Y/n]:{C_RESET} "
            ).strip().lower()

            new_params_json = None
            if edit_params in ("", "y", "yes"):
                print(
                    f"\n {C_BOLD}─── Task Parameters ───────────────────────────────{C_RESET}"
                )
                print(f" {C_DIM}Press Enter to keep current value shown in [ ]{C_RESET}\n")
                final_params = _prompt_task_params(current_params, schema_defaults)
                new_params_json = _j.dumps(final_params)
                print(f"\n {C_DIM}▶ Params: {new_params_json}{C_RESET}")

            # ── Apply ─────────────────────────────────────────────────────────
            args = ["tasks", "edit", "--id", str(t["id"])]
            has_change = False
            if new_name:
                args += ["--name", new_name]; has_change = True
            if new_interval is not None:
                args += ["--interval", str(new_interval)]; has_change = True
            if new_status:
                args += ["--status", new_status]; has_change = True
            if new_params_json is not None:
                args += ["--params", new_params_json]; has_change = True

            if has_change:
                run_cli_command(args)
            else:
                print(f"\n {C_DIM}No changes made.{C_RESET}")
                input(f"{C_DIM}Press Enter to return…{C_RESET}")

        # ── 9/10. Pause / Resume ALL ──────────────────────────────────────────
        elif c == "9":
            confirm = input(
                f" {C_YELLOW}Pause ALL background tasks? [y/N]:{C_RESET} "
            ).strip().lower()
            if confirm == "y":
                run_cli_command(["tasks", "pause-all"])

        elif c == "10":
            confirm = input(
                f" {C_GREEN}Resume ALL background tasks? [y/N]:{C_RESET} "
            ).strip().lower()
            if confirm == "y":
                run_cli_command(["tasks", "resume-all"])

        # ── 11. Remove ────────────────────────────────────────────────────────
        elif c == "11":
            t = _pick_task(tasks, "Task # or ID to remove")
            if t:
                confirm = input(
                    f" {C_RED}Remove task #{t['id']} '{t['name']}'? [y/N]:{C_RESET} "
                ).strip().lower()
                if confirm == "y":
                    run_cli_command(["tasks", "rm", "--id", str(t["id"])])

        # ── 12. Back ──────────────────────────────────────────────────────────
        elif c == "12":
            break



def menu_kill_switch():
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_RED}🚨 EMERGENCY KILL-SWITCH & BOT STOPPERS{C_RESET}\n")
    print(f"  {C_CYAN}1.{C_RESET} 🚨 Close ALL Open Exchange Positions (`bot-close-all`)")
    print(f"  {C_CYAN}2.{C_RESET} 🛑 Stop ALL Live Production Bots (`live`)")
    print(f"  {C_CYAN}3.{C_RESET} 🛑 Stop ALL Testnet Bots (`testnet`)")
    print(f"  {C_CYAN}4.{C_RESET} 🛑 Stop ALL Paper Bots (`paper`)")
    print(f"  {C_CYAN}5.{C_RESET} 🛑 Stop ALL Paper Live Bots (`paper_live`)")
    print(f"  {C_CYAN}6.{C_RESET} 🔴 Stop ALL Bots Across Every Venue")
    print(f"  {C_CYAN}7.{C_RESET} Back to Main Menu\n")
    
    c = input(f" {C_BOLD}Select option [1-7]:{C_RESET} ").strip()
    if c == "1":
        confirm = input(f" {C_RED}CLOSE ALL open exchange positions? [y/N]:{C_RESET} ").strip().lower()
        if confirm == "y": run_cli_command(["bot-close-all"])
    elif c == "2":
        confirm = input(f" {C_RED}Stop ALL Live production bots? [y/N]:{C_RESET} ").strip().lower()
        if confirm == "y": run_cli_command(["deployments", "stop-all", "--venue", "live"])
    elif c == "3":
        confirm = input(f" {C_RED}Stop ALL Testnet bots? [y/N]:{C_RESET} ").strip().lower()
        if confirm == "y": run_cli_command(["deployments", "stop-all", "--venue", "testnet"])
    elif c == "4":
        confirm = input(f" {C_RED}Stop ALL Paper bots? [y/N]:{C_RESET} ").strip().lower()
        if confirm == "y": run_cli_command(["deployments", "stop-all", "--venue", "paper"])
    elif c == "5":
        confirm = input(f" {C_RED}Stop ALL Paper Live bots? [y/N]:{C_RESET} ").strip().lower()
        if confirm == "y": run_cli_command(["deployments", "stop-all", "--venue", "paper_live"])
    elif c == "6":
        confirm = input(f" {C_RED}Stop ALL bots across ALL venues? [y/N]:{C_RESET} ").strip().lower()
        if confirm == "y": run_cli_command(["deployments", "stop-all"])

def main():
    while True:
        clear_screen()
        print_banner()
        print(f" {C_BOLD}MAIN MENU{C_RESET}\n")
        print(f"  {C_CYAN} 1.{C_RESET} 📈  {C_BOLD}Run Backtest{C_RESET}")
        print(f"  {C_CYAN} 2.{C_RESET} 🤖  {C_BOLD}Bot Manager & Deployments{C_RESET}")
        print(f"  {C_CYAN} 3.{C_RESET} ⏱️   {C_BOLD}Schedule Trade & Automated Execution{C_RESET}")
        print(f"  {C_CYAN} 4.{C_RESET} 📊  {C_BOLD}Portfolio PnL & Performance{C_RESET}")
        print(f"  {C_CYAN} 5.{C_RESET} 🏆  {C_BOLD}Strategy Leaderboard{C_RESET}")
        print(f"  {C_CYAN} 6.{C_RESET} 🖥️   {C_BOLD}Real-Time Console PnL Dashboard (Auto-refresh){C_RESET}")
        print(f"  {C_CYAN} 7.{C_RESET} 🔍  {C_BOLD}Market Scanner & Ranking{C_RESET}")
        print(f"  {C_CYAN} 8.{C_RESET} ⚙️   {C_BOLD}Background Tasks & Scheduler{C_RESET}")
        print(f"  {C_CYAN} 9.{C_RESET} 💼  {C_BOLD}Account Balances & Positions{C_RESET}")
        print(f"  {C_CYAN}10.{C_RESET} 🚀  {C_BOLD}Auto-Scan & Auto-Deploy{C_RESET}")
        print(f"  {C_CYAN}11.{C_RESET} 🚨  {C_RED}Emergency Kill-Switch (Close All Positions){C_RESET}")
        print(f"  {C_CYAN}12.{C_RESET} 🔄  {C_YELLOW}Factory Reset System (Clean Slate for New Users){C_RESET}")
        print(f"  {C_CYAN} 0.{C_RESET} 🚪  {C_DIM}Exit{C_RESET}\n")
        
        choice = input(f" {C_BOLD}Select option [0-12]:{C_RESET} ").strip()
        
        if choice == "1": menu_backtest()
        elif choice == "2": menu_deployments()
        elif choice == "3": menu_scheduled_trade()
        elif choice == "4": run_cli_command(["pnl"])
        elif choice == "5": run_cli_command(["pnl-strategy"])
        elif choice == "6": run_cli_command(["monitor"])
        elif choice == "7": menu_scanner()
        elif choice == "8": menu_tasks()
        elif choice == "9": run_cli_command(["folio"])
        elif choice == "10":
            top = input(f" {C_CYAN}Top N coins to deploy on [1]:{C_RESET} ").strip() or "1"
            venue = input(f" {C_CYAN}Target Venue (paper/paper_live/testnet/live) [testnet]:{C_RESET} ").strip() or "testnet"
            tf = input(f" {C_CYAN}Timeframe (1m/5m/15m/1h/4h) [15m]:{C_RESET} ").strip() or "15m"
            sl = input(f" {C_CYAN}Stop Loss % [1.2]:{C_RESET} ").strip() or "1.2"
            tp = input(f" {C_CYAN}Take Profit % [2.4]:{C_RESET} ").strip() or "2.4"
            trail = input(f" {C_CYAN}Trailing Stop % [0.8]:{C_RESET} ").strip() or "0.8"
            days = input(f" {C_CYAN}Lookback Days [7]:{C_RESET} ").strip() or "7"
            run_cli_command([
                "auto-deploy", "--top", top, "--venue", venue, "--timeframe", tf,
                "--sl-pct", sl, "--tp-pct", tp, "--trail-pct", trail, "--days", days
            ])
        elif choice == "11": menu_kill_switch()
        elif choice == "12":
            clear_screen()
            print_banner()
            print(f"{C_BOLD}{C_YELLOW}🔄 FACTORY RESET SYSTEM{C_RESET}\n")
            confirm = input(f" {C_RED}Are you sure you want to RESET the app to fresh out-of-the-box state? [y/N]:{C_RESET} ").strip().lower()
            if confirm == "y":
                run_cli_command(["factory-reset", "-y"])
        elif choice == "0":
            print(f"\n{C_GREEN}Exited Delta Console. Happy Trading!{C_RESET}\n")
            sys.exit(0)

if __name__ == "__main__":
    main()

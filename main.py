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
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_MAGENTA}📈 RUN STRATEGY BACKTEST{C_RESET}\n")
    
    strategy = select_strategy_interactive(default="supertrend_mom")
    symbol   = input(f" {C_CYAN}Symbol{C_RESET}   [BTCUSD]: ").strip() or "BTCUSD"
    tf       = input(f" {C_CYAN}Timeframe{C_RESET}[15m]: ").strip() or "15m"
    days     = input(f" {C_CYAN}Days{C_RESET}     [60]: ").strip() or "60"
    
    run_cli_command(["backtest", "--strategy", strategy, "--symbol", symbol, "--timeframe", tf, "--days", days])

def menu_scheduled_trade():
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_CYAN}⏱️ SCHEDULED TRADING & AUTOMATED EXECUTION{C_RESET}\n")
    print(f"  {C_CYAN}1.{C_RESET} Deploy Recurring Strategy Bot (Scheduled Execution)")
    print(f"  {C_CYAN}2.{C_RESET} One-Shot Strategy Evaluation & Immediate Order (`trade`)")
    print(f"  {C_CYAN}3.{C_RESET} Start Deployment Watcher Engine (`watch`)")
    print(f"  {C_CYAN}4.{C_RESET} Schedule New Background Task (`tasks add`)")
    print(f"  {C_CYAN}5.{C_RESET} List Active Scheduled Deployments")
    print(f"  {C_CYAN}6.{C_RESET} Back to Main Menu\n")
    
    c = input(f" {C_BOLD}Select [1-6]:{C_RESET} ").strip()
    if c == "1":
        name = input(f" {C_CYAN}Bot Name{C_RESET} [Scheduled Bot]: ").strip() or "Scheduled Bot"
        venue = input(f" {C_CYAN}Venue (testnet/live){C_RESET} [testnet]: ").strip() or "testnet"
        strategy = select_strategy_interactive(default="supertrend_mom")
        symbol = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
        tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
        size = input(f" {C_CYAN}Size{C_RESET} [0.001]: ").strip() or "0.001"
        interval = input(f" {C_CYAN}Schedule Interval (sec){C_RESET} [300]: ").strip() or "300"
        
        args = ["deployments", "add", "--name", name, "--venue", venue, "--strategy", strategy,
                "--symbol", symbol, "--resolution", tf, "--size", size, "--interval", interval]
        if venue == "live": args.append("--i-understand-live")
        run_cli_command(args)
    elif c == "2":
        venue = input(f" {C_CYAN}Venue (testnet/live){C_RESET} [testnet]: ").strip() or "testnet"
        strategy = select_strategy_interactive(default="smc_ob_fvg")
        symbol = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
        tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
        size = input(f" {C_CYAN}Size{C_RESET} [1]: ").strip() or "1"
        
        args = ["trade", "--venue", venue, "--strategy", strategy, "--symbol", symbol, "--resolution", tf, "--size", size]
        if venue == "live": args.append("--i-understand-live")
        run_cli_command(args)
    elif c == "3":
        interval = input(f" {C_CYAN}Watcher Loop Tick Interval (sec){C_RESET} [15]: ").strip() or "15"
        run_cli_command(["watch", "--interval", interval])
    elif c == "4":
        name = input(f" {C_CYAN}Task Name{C_RESET} [Risk Guard]: ").strip() or "Risk Guard"
        script = input(f" {C_CYAN}Script in delta_bt/tasks/{C_RESET} [emergency_monitor.py]: ").strip() or "emergency_monitor.py"
        interval = input(f" {C_CYAN}Execution Interval (sec){C_RESET} [300]: ").strip() or "300"
        run_cli_command(["tasks", "add", "--name", name, "--script", script, "--interval", interval])
    elif c == "5":
        run_cli_command(["deployments", "list"])

def menu_deployments():
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_GREEN}🤖 LIVE / PAPER BOTS & DEPLOYMENTS{C_RESET}\n")
    print(f"  {C_CYAN}1.{C_RESET} List Active Bots & PnL")
    print(f"  {C_CYAN}2.{C_RESET} Deploy New Scheduled Bot")
    print(f"  {C_CYAN}3.{C_RESET} Pause Bot")
    print(f"  {C_CYAN}4.{C_RESET} Resume Bot")
    print(f"  {C_CYAN}5.{C_RESET} Stop Bot")
    print(f"  {C_CYAN}6.{C_RESET} View Bot Events")
    print(f"  {C_CYAN}7.{C_RESET} Back to Menu\n")
    
    c = input(f" {C_BOLD}Select [1-7]:{C_RESET} ").strip()
    if c == "1": run_cli_command(["deployments", "list"])
    elif c == "2":
        name = input(f" {C_CYAN}Bot Name{C_RESET} [CLI Bot]: ").strip() or "CLI Bot"
        venue = input(f" {C_CYAN}Venue (testnet/live){C_RESET} [testnet]: ").strip() or "testnet"
        strategy = select_strategy_interactive(default="supertrend_mom")
        symbol = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
        tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
        size = input(f" {C_CYAN}Size{C_RESET} [0.001]: ").strip() or "0.001"
        
        args = ["deployments", "add", "--name", name, "--venue", venue, "--strategy", strategy,
                "--symbol", symbol, "--resolution", tf, "--size", size]
        if venue == "live": args.append("--i-understand-live")
        run_cli_command(args)
    elif c == "3":
        b_id = input(f" {C_CYAN}Bot ID to pause:{C_RESET} ").strip()
        if b_id: run_cli_command(["deployments", "pause", "--id", b_id])
    elif c == "4":
        b_id = input(f" {C_CYAN}Bot ID to resume:{C_RESET} ").strip()
        if b_id: run_cli_command(["deployments", "resume", "--id", b_id])
    elif c == "5":
        b_id = input(f" {C_CYAN}Bot ID to stop:{C_RESET} ").strip()
        if b_id: run_cli_command(["deployments", "stop", "--id", b_id])
    elif c == "6":
        b_id = input(f" {C_CYAN}Bot ID:{C_RESET} ").strip()
        if b_id: run_cli_command(["bot-show", "--id", b_id])

def menu_scanner():
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_YELLOW}🔍 MARKET SCANNER & RANKING{C_RESET}\n")
    print(f"  {C_CYAN}1.{C_RESET} Scan Parameter Grid for Symbol")
    print(f"  {C_CYAN}2.{C_RESET} Rank Top Market Gainers / Volume")
    print(f"  {C_CYAN}3.{C_RESET} Back to Menu\n")
    
    c = input(f" {C_BOLD}Select [1-3]:{C_RESET} ").strip()
    if c == "1":
        sym = input(f" {C_CYAN}Symbol{C_RESET} [BTCUSD]: ").strip() or "BTCUSD"
        tf = input(f" {C_CYAN}Timeframe{C_RESET} [15m]: ").strip() or "15m"
        run_cli_command(["scan", "--symbol", sym, "--timeframe", tf, "--top", "10"])
    elif c == "2":
        top = input(f" {C_CYAN}Top N Coins{C_RESET} [15]: ").strip() or "15"
        run_cli_command(["rank-universe", "--top", top])

def menu_tasks():
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_BLUE}⚙️ SCHEDULER & BACKGROUND TASKS{C_RESET}\n")
    print(f"  {C_CYAN}1.{C_RESET} List All Tasks")
    print(f"  {C_CYAN}2.{C_RESET} View Task Logs")
    print(f"  {C_CYAN}3.{C_RESET} Run Task Once Now")
    print(f"  {C_CYAN}4.{C_RESET} Pause Task")
    print(f"  {C_CYAN}5.{C_RESET} Resume Task")
    print(f"  {C_CYAN}6.{C_RESET} Schedule New Task")
    print(f"  {C_CYAN}7.{C_RESET} Edit Task (Interval / Name)")
    print(f"  {C_CYAN}8.{C_RESET} Back to Menu\n")
    
    c = input(f" {C_BOLD}Select [1-8]:{C_RESET} ").strip()
    if c == "1": run_cli_command(["tasks", "list"])
    elif c == "2":
        tid = input(f" {C_CYAN}Task ID:{C_RESET} ").strip()
        if tid: run_cli_command(["tasks", "logs", "--id", tid])
    elif c == "3":
        tid = input(f" {C_CYAN}Task ID:{C_RESET} ").strip()
        if tid: run_cli_command(["tasks", "run-now", "--id", tid])
    elif c == "4":
        tid = input(f" {C_CYAN}Task ID to pause:{C_RESET} ").strip()
        if tid: run_cli_command(["tasks", "pause", "--id", tid])
    elif c == "5":
        tid = input(f" {C_CYAN}Task ID to resume:{C_RESET} ").strip()
        if tid: run_cli_command(["tasks", "resume", "--id", tid])
    elif c == "6":
        name = input(f" {C_CYAN}Task Name{C_RESET} [Risk Guard]: ").strip() or "Risk Guard"
        script = input(f" {C_CYAN}Script Name in delta_bt/tasks/{C_RESET} [emergency_monitor.py]: ").strip() or "emergency_monitor.py"
        interval = input(f" {C_CYAN}Interval (sec){C_RESET} [300]: ").strip() or "300"
        run_cli_command(["tasks", "add", "--name", name, "--script", script, "--interval", interval])
    elif c == "7":
        tid = input(f" {C_CYAN}Task ID to edit:{C_RESET} ").strip()
        if tid:
            interval = input(f" {C_CYAN}New Interval (sec) (press Enter to skip):{C_RESET} ").strip()
            args = ["tasks", "edit", "--id", tid]
            if interval: args.extend(["--interval", interval])
            run_cli_command(args)

def menu_kill_switch():
    clear_screen()
    print_banner()
    print(f"{C_BOLD}{C_RED}🚨 EMERGENCY POSITION KILL-SWITCH{C_RESET}\n")
    confirm = input(f" {C_RED}Are you sure you want to CLOSE ALL open exchange positions? [y/N]:{C_RESET} ").strip().lower()
    if confirm == "y":
        run_cli_command(["bot-close-all"])

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
        print(f"  {C_CYAN} 6.{C_RESET} 🖥️   {C_BOLD}Live Terminal Monitor (Auto-refresh){C_RESET}")
        print(f"  {C_CYAN} 7.{C_RESET} 🔍  {C_BOLD}Market Scanner & Ranking{C_RESET}")
        print(f"  {C_CYAN} 8.{C_RESET} ⚙️   {C_BOLD}Background Tasks & Scheduler{C_RESET}")
        print(f"  {C_CYAN} 9.{C_RESET} 💼  {C_BOLD}Account Balances & Positions{C_RESET}")
        print(f"  {C_CYAN}10.{C_RESET} 🚀  {C_BOLD}Auto-Scan & Auto-Deploy{C_RESET}")
        print(f"  {C_CYAN}11.{C_RESET} 🚨  {C_RED}Emergency Kill-Switch (Close All){C_RESET}")
        print(f"  {C_CYAN} 0.{C_RESET} 🚪  {C_DIM}Exit{C_RESET}\n")
        
        choice = input(f" {C_BOLD}Select option [0-11]:{C_RESET} ").strip()
        
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
            run_cli_command(["auto-deploy", "--top", top])
        elif choice == "11": menu_kill_switch()
        elif choice == "0":
            print(f"\n{C_GREEN}Exited Delta Console. Happy Trading!{C_RESET}\n")
            sys.exit(0)

if __name__ == "__main__":
    main()

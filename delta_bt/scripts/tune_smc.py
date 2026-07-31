import sys
import os
import json
from datetime import datetime, timedelta, timezone

# Add python dir to path so we can import delta_bt
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from delta_bt.core.engine import run_backtest
from delta_bt.core.registry import load_strategy
from delta_bt.core.types import RunConfig
from delta_bt.data.delta_client import DeltaClient
from delta_bt.data.history import load_history
from delta_bt.reports.report import summarize

def main():
    client = DeltaClient(base_url="https://api.india.delta.exchange")
    symbol = "BTCUSD"
    resolution = "5m"
    
    end = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
    start = end - timedelta(days=7) # 7 days history
    
    print(f"Loading {symbol} {resolution} history from {start.date()} to {end.date()}...")
    bars = load_history(client, symbol, resolution, start, end)
    print(f"Loaded {len(bars)} bars.")
    
    if not bars:
        print("No bars loaded. Exiting.")
        return
        
    sl_pcts = [1.0, 1.5, 2.0]
    tp_pcts = [0.0, 2.0, 4.0]
    trail_pcts = [0.5, 1.0, 0.0]
    
    # We will test smc_ob
    strategy_name = "smc_ob"
    
    results = []
    
    print(f"Running grid search for {strategy_name}...")
    
    for sl in sl_pcts:
        for tp in tp_pcts:
            for tr in trail_pcts:
                cfg = RunConfig(
                    strategy=strategy_name,
                    symbol=symbol,
                    resolution=resolution,
                    capital=10000.0,
                    fee_bps=5.0,
                    slippage_bps=5.0,
                    qty_pct=1.0, # 100% equity
                    leverage=1.0,
                    sl_pct=sl,
                    tp_pct=tp,
                    trail_pct=tr,
                )
                
                strat = load_strategy(strategy_name, {})
                pf = run_backtest(bars, strat, cfg)
                
                # collect metrics
                sum_dict = summarize(pf)
                if "error" in sum_dict: continue
                
                results.append({
                    "sl": sl,
                    "tp": tp,
                    "trail": tr,
                    "trades": sum_dict.get("trades", 0),
                    "net_pnl": sum_dict.get("net_pnl", 0),
                    "win_rate": sum_dict.get("win_rate_pct", 0),
                    "profit_factor": sum_dict.get("profit_factor", 0),
                    "max_dd": sum_dict.get("max_drawdown_pct", 0),
                    "sharpe": sum_dict.get("sharpe", 0)
                })
                
    # Sort by net_pnl
    results.sort(key=lambda x: x["net_pnl"], reverse=True)
    
    print("\n--- TOP 5 CONFIGS ---")
    print(json.dumps(results[:5], indent=2))

if __name__ == "__main__":
    main()

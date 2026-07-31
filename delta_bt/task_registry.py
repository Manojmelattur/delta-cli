"""Task Registry & Metadata Catalog for Delta-BT Background Jobs.

Provides structured metadata for all task scripts under delta_bt/tasks/.
Dynamically scans the directory and categorizes tasks automatically.
"""
from typing import Dict, List, Any
import os
import glob

_HARDCODED_METADATA: List[Dict[str, Any]] = [
    {
        "script": "emergency_monitor.py",
        "name": "Emergency Risk Guard & Position Monitor",
        "category": "Risk & Security",
        "default_interval": 300,
        "desc": "Monitors open positions for stop-loss breaches, breakeven activations, trailing stops, and margin spikes.",
        "params": {"venue": "testnet", "max_margin_utilization": 0.8}
    },
    {
        "script": "daily_report.py",
        "name": "Daily PnL & Performance Report",
        "category": "Reporting",
        "default_interval": 86400,
        "desc": "Generates a daily summary of realized PnL, win rate, fees paid, and prints it to logs or sends a webhook.",
        "params": {"run_at_hour_utc": 0, "webhook_url": ""}
    },
    {
        "script": "stale_bot_cleaner.py",
        "name": "Stale Bot & Zombie Process Cleaner",
        "category": "System Maintenance",
        "default_interval": 3600,
        "desc": "Finds bots stuck in 'running' state with no recent ticks and auto-pauses them. Pauses tasks that keep crashing.",
        "params": {"max_stale_minutes": 30}
    },
    {
        "script": "db_vacuum.py",
        "name": "Database VACUUM & Optimize",
        "category": "System Maintenance",
        "default_interval": 86400 * 3,
        "desc": "Runs SQLite VACUUM and ANALYZE to reclaim disk space and rebuild query plans.",
        "params": {}
    },
    {
        "script": "leverage_audit.py",
        "name": "Exchange Leverage Sync Audit",
        "category": "Risk & Security",
        "default_interval": 600,
        "desc": "Ensures the leverage set in local bot deployments matches the actual isolated margin leverage on the Delta exchange.",
        "params": {"venue": "testnet"}
    },
    {
        "script": "funding_rate_monitor.py",
        "name": "Extreme Funding Rate Alert",
        "category": "Market Monitors",
        "default_interval": 3600,
        "desc": "Scans perp markets for extreme negative or positive funding rates indicating potential squeezes.",
        "params": {"alert_threshold_pct": 0.1, "webhook_url": ""}
    },
    {
        "script": "liquidation_cascade_hunter.py",
        "name": "Liquidation Cascade Hunter",
        "category": "Market Monitors",
        "default_interval": 60,
        "desc": "Monitors websocket tape for massive liquidation clusters to trigger counter-trend scalps.",
        "params": {"min_liquidation_usd": 100000}
    },
    {
        "script": "fear_greed_monitor.py",
        "name": "Crypto Fear & Greed Index Tracker",
        "category": "Market Monitors",
        "default_interval": 86400,
        "desc": "Fetches daily Fear & Greed index. Pauses long-only bots if index > 85 (Extreme Greed).",
        "params": {"pause_longs_above": 85, "pause_shorts_below": 15}
    },
    {
        "script": "api_health_check.py",
        "name": "Exchange API Health & Latency",
        "category": "System Maintenance",
        "default_interval": 120,
        "desc": "Pings the Delta API. If latency > 1000ms or 5xx errors occur, triggers system-wide pause.",
        "params": {"max_latency_ms": 1000, "venue": "testnet"}
    },
    {
        "script": "strategy_tuner_task.py",
        "name": "Auto-Hyperparameter Tuner (Nightly)",
        "category": "Optimization",
        "default_interval": 86400,
        "desc": "Runs parameter grid sweeps on all active strategies overnight and updates deployment params_json for the next day.",
        "params": {"lookback_days": 14, "target_metric": "sharpe"}
    },
    {
        "script": "pnl_attribution.py",
        "name": "PnL Attribution & Factor Analysis",
        "category": "Reporting",
        "default_interval": 43200,
        "desc": "Analyzes portfolio returns to determine how much PnL came from Beta (market trend) vs Alpha (strategy edge).",
        "params": {"benchmark_symbol": "BTCUSD"}
    },
    {
        "script": "deployment_snapshot.py",
        "name": "Deployment Config Backup",
        "category": "System Maintenance",
        "default_interval": 86400,
        "desc": "Dumps the `deployments` table to a JSON backup file in case of database corruption.",
        "params": {"keep_backups_days": 7}
    },
    {
        "script": "news_blackout.py",
        "name": "Macro News Blackout Enforcer",
        "category": "Risk & Security",
        "default_interval": 3600,
        "desc": "Checks ForexFactory/Economic calendars. Pauses bots 15m before CPI/FOMC and resumes 15m after.",
        "params": {"pre_event_minutes": 15, "post_event_minutes": 15}
    },
    {
        "script": "volatility_circuit_breaker.py",
        "name": "Market Volatility Circuit Breaker",
        "category": "Risk & Security",
        "default_interval": 60,
        "desc": "If BTC drops > 5% in 5 minutes, triggers a global panic pause on all bot deployments.",
        "params": {"symbol": "BTCUSD", "drop_pct_threshold": 5.0, "time_window_min": 5}
    },
    {
        "script": "auto_scan_one_cycle.py",
        "name": "Auto-Scan One Cycle (Hunter)",
        "category": "Hunters & Snipers",
        "default_interval": 900,
        "desc": "Scans market for top setup, deploys a 'one-shot' bot, and waits for it to close before hunting again.",
        "params": {"top_n": 5, "timeframe": "15m", "venue": "testnet"}
    },
]

_CACHED_CATALOG = None

def get_catalog() -> List[Dict[str, Any]]:
    """Returns the full list of task metadata, dynamically built from delta_bt/tasks."""
    global _CACHED_CATALOG
    if _CACHED_CATALOG is not None:
        return _CACHED_CATALOG

    meta_map = {m["script"]: m for m in _HARDCODED_METADATA}
    
    base_dir = os.path.dirname(__file__)
    tasks_dir = os.path.join(base_dir, "tasks")
    py_files = glob.glob(os.path.join(tasks_dir, "*.py"))
    
    catalog = []
    
    for pf in sorted(py_files):
        script = os.path.basename(pf)
        if script.startswith("__") or not script.endswith(".py"):
            continue
            
        if script in meta_map:
            catalog.append(meta_map[script])
            continue
            
        name = script.replace(".py", "").replace("_", " ").title()
        
        script_lower = script.lower()
        if "hunter" in script_lower or "sniper" in script_lower:
            category = "Hunters & Snipers"
        elif "scan" in script_lower or "arb" in script_lower or "farmer" in script_lower:
            category = "Market Scanners"
        elif "guard" in script_lower or "limit" in script_lower or "monitor" in script_lower or "risk" in script_lower or "breaker" in script_lower:
            category = "Risk & Security"
        elif "deploy" in script_lower or "alloc" in script_lower or "sizer" in script_lower:
            category = "Execution & Sizing"
        else:
            category = "General Tasks"
            
        default_params = {}
        if category in ("Hunters & Snipers", "Market Scanners"):
            default_params = {"venue": "testnet", "base_lot_size": 1, "top_n_symbols": 15}
        elif category == "Risk & Security":
            default_params = {"venue": "testnet"}
            
        catalog.append({
            "script": script,
            "name": name,
            "category": category,
            "default_interval": 3600,
            "desc": f"Custom task script ({category}).",
            "params": default_params
        })
        
    _CACHED_CATALOG = catalog
    return catalog

def get_task_metadata(script_name: str) -> Dict[str, Any]:
    """Returns metadata for a specific script name, or a default dict if not found."""
    catalog = get_catalog()
    for task in catalog:
        if task["script"] == script_name:
            return task
    
    # Fallback for unknown scripts
    name = script_name.replace(".py", "").replace("_", " ").title()
    return {
        "script": script_name,
        "name": name,
        "category": "Custom Script",
        "default_interval": 3600,
        "desc": "Unknown custom script loaded by user.",
        "params": {}
    }

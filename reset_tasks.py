import sqlite3
from delta_bt.store.db import _resolve_db

def run():
    db_path = _resolve_db()
    tasks = [
        ("Emergency Monitor", "Monitors live bot positions for extreme drawdowns and issues FLAT overrides.", 900, "emergency_monitor", "{}"),
        ("Daily Report", "Generates a daily summary of bot activity.", 86400, "daily_report", "{}"),
        ("Stat Arb Scanner", "Calculates Z-Scores on correlated pairs and deploys mean reversion on divergences.", 300, "stat_arb_scanner", '{"base_lot_size": 1.0, "auto_deploy": false}'),
        ("Efficiency Evaluator", "Analyzes historical trades to measure the impact of institutional risk-management features.", 3600, "efficiency_evaluator", "{}"),
        ("Scalp Hunter", "Searches for volatile scalping opportunities and deploys short-term bots.", 60, "scalp_hunter", "{}"),
        ("Capital Allocator", "Rebalances strategy capital based on historical win-rates and profit factors.", 14400, "capital_allocator", "{}"),
        ("Equity Monitor", "Tracks open position drawdown and closed trade equity curves for all running bots.", 300, "equity_monitor", "{}"),
        ("Funding Rate Monitor", "Monitors extreme funding rates across perpetual pairs to highlight arbitrage opportunities.", 3600, "funding_rate_monitor", "{}"),
        ("Global Exposure Manager", "Enforces portfolio-wide position limits and total USD exposure ceilings.", 600, "global_exposure_manager", "{}"),
        ("Liquidity Guard", "Monitors order book depth and warns when market order slippage exceeds thresholds.", 300, "liquidity_guard", "{}"),
        ("MTF Trend Enforcer", "Validates higher timeframe EMAs to ensure sub-minute strategies trade in line with trend.", 900, "mtf_trend_enforcer", "{}"),
        ("Runner Fleet Hunter", "Scans top turnover pairs for SMC setups and deploys long-term trend runner bots.", 300, "runner_fleet_hunter", "{}"),
        ("SMC Hunter", "Scans order blocks and fair value gaps across top pairs to discover SMC entries.", 300, "smc_hunter", "{}"),
        ("Volatility Circuit Breaker", "Monitors market flash crashes and pauses long bots during extreme market dips.", 120, "volatility_circuit_breaker", "{}"),
        ("Volatility Grid Farmer", "Identifies ranging high-volatility pairs suitable for automated grid farming.", 1800, "volatility_grid_farmer", "{}"),
        ("Volume Anomaly Sniper", "Detects sudden 5x volume spikes to capture explosive momentum breakouts.", 60, "volume_anomaly_sniper", "{}"),
        ("VWAP Reversion Hunter", "Monitors price deviations from VWAP bands to deploy mean reversion trades.", 600, "vwap_reversion_hunter", "{}"),
        ("Hyperparameter Auto-Tuner", "Periodically backtests historical candle data to auto-tune optimal SL/TP/Trailing Risk parameters.", 86400, "hyperparam_auto_tuner", '{"lookback_days": 30, "auto_apply": false}'),
        ("Liquidation Cascade Hunter", "Scans forced liquidation wicks (>3.5%) to deploy fast mean-reversion scalp bounces.", 300, "liquidation_cascade_hunter", "{}"),
        ("Funding Arbitrage Farmer", "Monitors high positive perpetual funding rates (>20% APY) for delta-neutral yield farming.", 3600, "funding_arbitrage_farmer", "{}"),
        ("Correlation Matrix Analyzer", "Calculates 30-day rolling correlations across active bots to prevent over-concentrated drawdown risks.", 14400, "correlation_matrix_analyzer", "{}"),
        ("ATR Position Sizer", "Calculates 14-period ATR across active bot symbols to maintain equal $ USD risk per trade.", 3600, "atr_position_sizer", "{}"),
        ("Webhook Dispatcher", "Dispatches real-time trade alerts and emergency notifications to Telegram & Discord webhooks.", 60, "webhook_dispatcher", "{}"),
        ("Options Delta Hedger", "Monitors net options portfolio Delta and auto-hedges via perpetual futures when Delta drifts.", 300, "options_delta_hedger", "{}"),
    ]
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DELETE FROM background_tasks")
        for name, desc, interval, script, params in tasks:
            conn.execute(
                "INSERT INTO background_tasks(name, description, interval_sec, status, script_name, params_json) VALUES (?, ?, ?, 'running', ?, ?)",
                (name, desc, interval, script, params)
            )
        conn.commit()
    print("Successfully cleared and re-seeded all 17 default background tasks!")

if __name__ == "__main__":
    run()

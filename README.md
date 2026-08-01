# ⚡ Delta Backtester — Standalone Console CLI Framework (`delta-cli`)

A pure-Python, **100% Terminal-Based** algorithmic backtesting, paper-trading, live-execution, market scanner, background task manager, and PnL analytics framework for **Delta Exchange India**.

> **Zero Web Dependencies Required**: `delta-cli` is completely decoupled and self-contained. It requires **no Node.js, no React, no Vite, and no Nginx**. You can safely run it on local machines or cloud servers (`/home/ubuntu/delta-cli`) as a standalone Git repository.

---

## 📋 Table of Contents
1. [Prerequisites & Quick Start](#1-prerequisites--quick-start)
2. [Environment Configuration (`.env` & `config.py`)](#2-environment-configuration-env--configpy)
3. [Interactive Terminal Menu (`./run.sh`)](#3-interactive-terminal-menu-runsh)
4. [Complete CLI Commands Reference](#4-complete-cli-commands-reference)
   - [Backtesting & Parameter Sweeps](#backtesting--parameter-sweeps)
   - [Live & Paper Trading Execution](#live--paper-trading-execution)
   - [Scheduled Execution & Headless Watcher](#scheduled-execution--headless-watcher)
   - [Bot & Deployment Management](#bot--deployment-management)
   - [Bot & Deployment Multi-Filter System](#bot--deployment-multi-filter-system)
   - [Terminal Monitoring & Emergency Kill-Switches](#terminal-monitoring--emergency-kill-switches)
   - [Portfolio PnL & Performance Analytics](#portfolio-pnl--performance-analytics)
   - [Universe Ranking & Market Scanning](#universe-ranking--market-scanning)
   - [Background Task Scheduler & Batch Commands (`tasks`)](#background-task-scheduler--batch-commands-tasks)
   - [Master Factory Reset (`factory-reset`)](#master-factory-reset-factory-reset)
   - [Database Maintenance & Utilities](#database-maintenance--utilities)
5. [Complete Strategies Catalog (30+ Strategies)](#5-complete-strategies-catalog-30-strategies)
6. [Complete Background Tasks Catalog (25 Active Tasks)](#6-complete-background-tasks-catalog-25-active-tasks)
7. [24/7 Cloud Server Operations & Headless Daemons](#7-247-cloud-server-operations--headless-daemons)

---

## 1. Prerequisites & Quick Start

### Requirements:
* Python **3.10+** (Python 3.11, 3.12, or 3.14 supported)
* `pip` and `venv`

### One-Step Launch (Linux / macOS / Git Bash):
```bash
cd delta-cli
chmod +x run.sh main.py
./run.sh
```

### Manual Environment Setup:
```bash
cd delta-cli
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 2. Environment Configuration (`.env` & `config.py`)

Credentials and configuration parameters are loaded through the central `delta_bt/config.py` module, which automatically reads from `.env`.

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Configure your credentials in `.env`:
```env
# Testnet Venue Credentials (https://testnet.delta.exchange)
DELTA_TESTNET_API_KEY=your_testnet_key
DELTA_TESTNET_API_SECRET=your_testnet_secret

# Production Live Venue Credentials (https://india.delta.exchange)
DELTA_LIVE_API_KEY=your_live_key
DELTA_LIVE_API_SECRET=your_live_secret

# Static IP Relay URL (Optional)
DELTA_LIVE_RELAY_URL=http://43.229.91.64
DELTA_RELAY_URL=http://43.229.91.64

# Telegram Bot Notifications (Optional)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Database & Redis Settings (Optional)
DELTA_BT_DB=/path/to/delta_bt.sqlite
REDIS_URL=redis://localhost:6379/0
```

---

## 3. Interactive Terminal Menu (`./run.sh`)

Launch the keyboard-driven interactive terminal menu:
```bash
./run.sh
```

Features clean ANSI color-coded tables and interactive single-key navigation:
* `1. 📈 Run Backtest`: Launch historical simulations with interactive strategy picker & custom risk knobs.
* `2. 🤖 Bot Manager & Deployments`: List, add, pause single/all, resume single/all, or stop single/all trading bots.
* `3. ⏱️ Schedule Trade & Automated Execution`: Deploy scheduled bots, one-shot strategy trades, or launch 24/7 headless watcher daemons.
* `4. 📊 Portfolio PnL & Performance`: View portfolio PnL summary, win rates, and ASCII equity chart.
* `5. 🏆 Strategy Leaderboard`: Compare strategy performance across past runs.
* `6. 🖥️ Live Terminal Monitor`: Real-time streaming monitor for active bots and open positions.
* `7. 🔍 Market Scanner & Ranking`: Rank tradable assets by volume, ADX regime, and ATR.
* `8. ⚙️ Background Tasks & Scheduler`: Inspect, trigger, edit intervals, pause single/all, resume single/all, or view logs for background jobs.
* `9. 💼 Account Balances & Positions`: Check live wallet balance and open position state across testnet and live.
* `10. 🚀 Auto-Scan & Auto-Deploy`: Automatically sweep markets with custom timeframes (1m-1d) and risk parameters, deploying best strategy to paper/testnet/live.
* `11. 🚨 Emergency Kill-Switch`: Instant emergency closing of all exchange positions.
* `12. 🔄 Factory Reset System`: Clean slate master reset for new users (clears DB, resets tasks, purges reports).

---

## 4. Complete CLI Commands Reference

All subcommands are executed using `python -m delta_bt <command> [options]`.

---

### Backtesting & Parameter Sweeps

#### `backtest`
Run a historical simulation on OHLC candles for a specific strategy.
```bash
# Basic backtest on BTC 15m over last 60 days
python -m delta_bt backtest --strategy supertrend_mom --symbol BTCUSD --timeframe 15m --days 60

# Backtest with risk management knobs (Stop Loss, Take Profit, Trailing Stop, Leverage)
python -m delta_bt backtest --strategy ema_cross --symbol ETHUSD --timeframe 15m --days 30 \
  --sl-pct 1.5 --tp-pct 3.0 --trail-pct 1.0 --leverage 3

# Pass custom strategy JSON parameters
python -m delta_bt backtest --strategy rsi_mr --symbol SOLUSD --timeframe 15m --days 60 \
  --params '{"period":14,"oversold":30,"overbought":70}'

# Specific start/end date range
python -m delta_bt backtest --strategy smc_ob_fvg --symbol BTCUSD --timeframe 1h \
  --start "2026-01-01 00:00:00" --end "2026-06-01 00:00:00"
```

#### `scan`
Scan and backtest **ALL** available strategies on a single symbol/timeframe to find the best performer.
```bash
# Scan all strategies on BTC 15m (last 60 days)
python -m delta_bt scan --symbol BTCUSD --timeframe 15m --days 60

# Save runs to SQLite, filter top 5 profitable strategies
python -m delta_bt scan --symbol ETHUSD --timeframe 1h --days 90 --profitable-only --top 5 --save

# Apply ADX regime filter during scan
python -m delta_bt scan --symbol SOLUSD --timeframe 15m --days 30 --adx-filter --adx-trend-min 25.0
```

#### `sweep`
Run a parameter sweep across all strategies on a symbol and output a formatted leaderboard sorted by PnL, Sharpe, win rate, or drawdown inside a clean Unicode boxed table.
```bash
python -m delta_bt sweep --symbol BTCUSD --resolution 15m --days 30 --sort sharpe --top 10 --csv ./reports/sweep.csv
```

#### `list-strategies`
List every available strategy module, version, and description.
```bash
python -m delta_bt list-strategies
```

---

### Live & Paper Trading Execution

#### `paper`
Launch a paper trading bot simulating orders in memory using live market feeds.
```bash
python -m delta_bt paper --strategy supertrend_mom --symbol BTCUSD --timeframe 15m --capital 10000
```

#### `live`
Launch a live trading bot sending real orders to Delta Exchange (requires `--i-understand-live`).
```bash
python -m delta_bt live --strategy smc_ob_fvg --symbol BTCUSD --timeframe 15m --lot 1 --i-understand-live
```

#### `trade`
Evaluate strategy signals on recent candles and place a one-shot market order.
```bash
# Trade on testnet
python -m delta_bt trade --venue testnet --strategy smc_ob_fvg --symbol BTCUSD --resolution 15m --lot 1

# Trade on live
python -m delta_bt trade --venue live --strategy supertrend_mom --symbol ETHUSD --resolution 15m --lot 10 --i-understand-live
```

---

### Scheduled Execution & Headless Watcher

#### `watch`
Run the 24/7 continuous deployment scheduler loop.
```bash
# Foreground execution
python -m delta_bt watch --interval 15

# Headless background execution (survives terminal exit / SIGHUP)
nohup python -m delta_bt watch --interval 15 > watcher.log 2>&1 &
```

---

### Bot & Deployment Management

#### `deployments add`
Deploy a new scheduled trading bot.
```bash
# Paper trading deployment
python -m delta_bt deployments add --name "Paper Grid Bot" --venue paper --strategy grid --symbol BTCUSD --lot 1

# Testnet deployment
python -m delta_bt deployments add --name "Testnet SMC" --venue testnet --strategy smc_ob_fvg --symbol ETHUSD --lot 10

# Live deployment
python -m delta_bt deployments add --name "Live Trend" --venue live --strategy supertrend_mom --symbol BTCUSD --lot 1 --i-understand-live

# One-Shot Deployment (Auto-stops bot after a single complete trade cycle)
python -m delta_bt deployments add --name "One Shot Sniper" --venue live --strategy supertrend_mom --symbol BTCUSD --lot 1 --sl-pct 1.5 --tp-pct 3.0 --params '{"one_shot": true}' --i-understand-live
```

#### Batch Control (`pause-all`, `resume-all`, `stop-all`)
```bash
# Pause all active bots
python -m delta_bt deployments pause-all

# Resume all paused bots
python -m delta_bt deployments resume-all

# Stop all active bots
python -m delta_bt deployments stop-all
```

#### Single Bot Control
```bash
# View bot details (supports both `1` and `--id 1` syntax)
python -m delta_bt bot-show 1
python -m delta_bt bot-show --id 1

# Pause / resume / stop specific bot
python -m delta_bt deployments pause --id 1
python -m delta_bt deployments resume --id 1
python -m delta_bt deployments stop --id 1
```

---

### Bot & Deployment Multi-Filter System

Filter active bots dynamically by status, venue, strategy, or symbol:
```bash
# Filter by venue
python -m delta_bt deployments list --venue testnet

# Filter by strategy
python -m delta_bt deployments list --strategy smc_ob_fvg

# Filter active running bots for a specific symbol
python -m delta_bt bots --symbol BTCUSD --status running

# Filter stopped/paused bots on paper
python -m delta_bt bots --all --status stopped --venue paper
```

---


### Restart
`sudo systemctl restart delta-cli`

### Terminal Monitoring & Emergency Kill-Switches

#### `monitor`
Launch real-time streaming terminal dashboard with live ANSI tables.
```bash
python -m delta_bt monitor
```

#### `bot-close-all` (Emergency Kill-Switch)
Close all active exchange positions immediately.
```bash
python -m delta_bt bot-close-all
```

---

### Portfolio PnL & Performance Analytics

#### `pnl`
Show portfolio PnL summary, win rates, and ASCII equity curve chart.
```bash
python -m delta_bt pnl --days 30
```

#### `pnl-strategy`
Break down realized PnL, trades, and win rates per strategy.
```bash
python -m delta_bt pnl-strategy
```

#### `folio`
Display wallet balances and open positions across testnet and live.
```bash
python -m delta_bt folio --venue both
```

---

### Universe Ranking & Market Scanning

#### `rank-universe`
Rank tradable crypto perpetuals by volume, ADX regime, and ATR volatility.
```bash
python -m delta_bt rank-universe --top 15 --lookback-bars 24 --resolution 1h
```

#### `auto-deploy`
Automatically scan top coins, sweep strategies across specified days/timeframe/SL/TP, and deploy the best strategy:
```bash
# Auto-deploy to testnet over 7 days at 15m timeframe
python -m delta_bt auto-deploy --top 1 --venue testnet --days 7 --timeframe 15m

# Auto-deploy to paper with custom SL/TP/Trailing stop
python -m delta_bt auto-deploy --top 1 --venue paper --days 3 --timeframe 5m --sl-pct 1.5 --tp-pct 3.0 --trail-pct 1.0
```

---

### Background Task Scheduler & Batch Commands (`tasks`)

#### `tasks list`
List all background tasks and last execution timestamps.
```bash
python -m delta_bt tasks list
```

#### `tasks edit`
Update execution interval, name, or status of an existing task:
```bash
python -m delta_bt tasks edit --id 5 --interval 120
```

#### Batch Control (`pause-all`, `resume-all`)
```bash
python -m delta_bt tasks pause-all
python -m delta_bt tasks resume-all
```

#### Single Task Control
```bash
# Force-run a task once right now
python -m delta_bt tasks run-now --id 5

# View real-time logs for a task
python -m delta_bt tasks logs --id 5 --limit 20
```

---

### Master Factory Reset (`factory-reset`)

Reset the application database, purges bot deployments, re-seeds default task workers, and cleans report CSVs to prepare a clean slate for a new user:
```bash
python -m delta_bt factory-reset -y
```

---

### Database Maintenance & Utilities

#### `db-info` & `db-vacuum`
```bash
# Print SQLite database path and table row counts
python -m delta_bt db-info

# Reclaim unused disk space and optimize indexes
python -m delta_bt db-vacuum
```

---

## 5. Complete Strategies Catalog (30+ Strategies)

All 29 strategies built into `delta-cli` are modular and supported across Backtest, Paper, Testnet, Live, and Auto-Deploy modes:

### Smart Money Concepts (SMC) & Institutional Flow
* **`smc_ob_fvg`**: Order Block + Fair Value Gap confluence entry.
* **`smc_ob`**: Institutional Order Block retest & trap.
* **`smc_choch_bos`**: Change of Character & Break of Structure.
* **`smc_liquidity_sweep`**: Stop-loss liquidity sweep hunter.
* **`smc_bos_retest`**: Structure break & body close retest.
* **`fvg`**: Fair Value Gap 3-candle imbalance fill.

### Price Action & Candlesticks
* **`price_action_pinbar`**: Pin bar long-wick support/resistance rejection.
* **`price_action_engulfing`**: Bullish/Bearish engulfing pattern momentum.

### Trend Following & Momentum
* **`supertrend_mom`**: ATR SuperTrend volatility trailing stop.
* **`supertrend_mom_v2`**: Multi-timeframe trend-filtered SuperTrend.
* **`ema_cross`**: Fast/Slow EMA crossover system.
* **`ema3`**: Triple EMA (9/21/50) alignment system.
* **`ema_rsi`**: Dual EMA trend + RSI momentum filter.
* **`sma_rsi`**: Dual SMA trend + RSI momentum filter.
* **`ichimoku_cloud`**: Ichimoku Kinko Hyo cloud breakout.
* **`turtle`**: Donchian channel breakout trend follower.

### Volatility, Grid & Mean Reversion
* **`grid`**: Automated laddered buy/sell grid farmer.
* **`rsi_mr`**: Oversold (<25) / Overbought (>75) RSI mean reversion.
* **`bollinger`**: Bollinger Band outer band bounce mean reversion.
* **`keltner_squeeze`**: Bollinger inside Keltner channel volatility squeeze.
* **`vwap`**: Daily institutional VWAP baseline mean reversion.
* **`vwap_bands`**: VWAP standard deviation band over-extension.
* **`bb_ha_supertrend`**: Heikin-Ashi smooth candles + Bollinger + SuperTrend.

### Divergence Oscillators
* **`macd`**: MACD histogram & signal line crossover.
* **`macd_divergence`**: Regular & hidden MACD divergence detector.
* **`rsi_divergence`**: Regular & hidden RSI divergence detector.
* **`momentum_breakout`**: High-volume 2x breakout sniper.

### Derivatives & Volatility Options
* **`move_volatility_straddle`**: MOVE volatility contract event straddle.
* **`options_iron_condor`**: Delta Options Iron Condor theta decay yield.

---

## 6. Complete Background Tasks Catalog (25 Active Tasks)

1. **Emergency Monitor**: Position liquidation guard & margin spike monitor.
2. **Daily Report**: End-of-day PnL report generator & Telegram dispatcher.
3. **Stat Arb Scanner**: Statistical arbitrage pair scanner.
4. **Efficiency Evaluator**: Execution efficiency & slippage analyzer.
5. **Scalp Hunter**: 1m high-frequency scalp setup scanner.
6. **Capital Allocator**: Dynamic capital allocation based on Sharpe ratio.
7. **Equity Monitor**: Account equity curve & drawdown tracker.
8. **Funding Rate Monitor**: Perpetual funding rate yield monitor.
9. **Global Exposure Manager**: Portfolio-wide maximum leverage & exposure cap manager.
10. **Liquidity Guard**: Orderbook depth & slippage guard.
11. **MTF Trend Enforcer**: Multi-timeframe trend alignment validator.
12. **Runner Fleet Hunter**: Trending coin runner bot deployer.
13. **SMC Hunter**: Smart Money Concepts entry scanner.
14. **Volatility Circuit Breaker**: Sudden market crash halt manager.
15. **Volatility Grid Farmer**: High-volatility dynamic grid deployer.
16. **Volume Anomaly Sniper**: Institutional volume spike detector.
17. **VWAP Reversion Hunter**: Extreme VWAP deviation mean reversion scanner.
18. **Hyperparameter Auto-Tuner**: Automated strategy parameter tuner.
19. **Liquidation Cascade Hunter**: Liquidation cascade counter-trend hunter.
20. **Funding Arbitrage Farmer**: Funding rate yield arbitrage farmer.
21. **Correlation Matrix Analyzer**: Cross-asset correlation risk manager.
22. **ATR Position Sizer**: Dynamic ATR volatility position sizer.
23. **Webhook Dispatcher**: Real-time Telegram/Webhook alert dispatcher.
24. **Options Delta Hedger**: Options portfolio delta-hedger.
25. **Risk Guard**: Emergency position risk guard.

---

## 7. 24/7 Cloud Server Operations & Headless Daemons

To run `delta-cli` 24/7 continuous on a cloud VPS (AWS, DigitalOcean, Hetzner) without relying on an active SSH connection:

### Method 1: Using `./run.sh` -> Menu Option 3 -> Sub-Option 4
Launches a background daemon using `nohup` that logs to `watcher.log` and survives terminal disconnect.

### Method 2: Using `tmux`
```bash
# 1. Create tmux session
tmux new -s delta_bot

# 2. Launch watcher engine
./run.sh

# 3. Detach from session: Press Ctrl+B then D
```
*Reconnect anytime*: `tmux attach -t delta_bot`

### Method 3: `systemd` Background Service
Create `/etc/systemd/system/delta-bot.service`:
```ini
[Unit]
Description=Delta Exchange Algorithmic Bot Watcher Engine
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/delta-cli
ExecStart=/home/ubuntu/delta-cli/venv/bin/python -m delta_bt watch --interval 15
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable --now delta-bot
```

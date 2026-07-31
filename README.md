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
   - [Bot & Deployment Management](#bot--deployment-management)
   - [Terminal Monitoring & Emergency Kill-Switch](#terminal-monitoring--emergency-kill-switch)
   - [Portfolio PnL & Performance Analytics](#portfolio-pnl--performance-analytics)
   - [Universe Ranking & Market Scanning](#universe-ranking--market-scanning)
   - [Background Task Scheduler (`tasks`)](#background-task-scheduler-tasks)
   - [Database Maintenance & Utilities](#database-maintenance--utilities)
5. [Complete Strategies Catalog (30+ Strategies)](#5-complete-strategies-catalog-30-strategies)
6. [Complete Background Tasks Catalog (60+ Tasks)](#6-complete-background-tasks-catalog-60-tasks)
7. [24/7 Cloud Server Operations](#7-247-cloud-server-operations)

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

Features clean ANSI color-coded tables and single-key navigation:
* `1. 📈 Run Backtest`: Launch historical simulations with custom risk parameters.
* `2. 🤖 Bot Manager & Deployments`: View, add, pause, resume, or remove live/paper bots.
* `3. 📊 Portfolio PnL & Performance`: View portfolio summary, win rates, and ASCII equity chart.
* `4. 🏆 Strategy Leaderboard`: Compare strategy performance across past runs.
* `5. 🖥️ Live Terminal Monitor`: Real-time streaming monitor for active bots and open positions.
* `6. 🔍 Market Scanner & Ranking`: Rank tradable assets by volume, ADX regime, and ATR.
* `7. ⚙️ Background Tasks & Scheduler`: Inspect, trigger, pause, or view logs for background jobs.
* `8. 💼 Account Balances & Positions`: Check live wallet balance and open position state.
* `9. 🚀 Auto-Scan & Auto-Deploy`: Automatically sweep markets and deploy optimal strategy bots.
* `10. 🚨 Emergency Kill-Switch`: Instant emergency reduction and closing of all exchange positions.

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
Run a parameter sweep across all strategies on a symbol and output a formatted leaderboard sorted by PnL, Sharpe, win rate, or drawdown.
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
Stream live candle data (testnet/demo) and execute paper trades in real-time.
```bash
# Paper trade Supertrend Momentum on BTC 1m for 1 hour (3600s)
python -m delta_bt paper --strategy supertrend_mom --symbol BTCUSD --timeframe 1m --duration 3600

# Paper trade with real testnet orders posted to exchange
python -m delta_bt paper --strategy ema3 --symbol BTCUSD --timeframe 5m --live-orders --live-qty 1
```

#### `trade`
Evaluate a strategy on recent candles and place a one-shot trade if entry criteria met.
```bash
python -m delta_bt trade --venue testnet --strategy smc_ob_fvg --symbol SOLUSD --resolution 1h --size 1
```

#### `live`
Run live automated execution on production exchange with real funds.
```bash
python -m delta_bt live --strategy supertrend_mom --symbol BTCUSD --timeframe 15m --live-qty 1 --i-understand
```

#### `order`
Place a manual immediate market or limit order without strategy evaluation.
```bash
# Place Market Order on Testnet
python -m delta_bt order --venue testnet --symbol SOLUSD --side buy --size 1 --type market_order

# Place Limit Order on Live Exchange
python -m delta_bt order --venue live --symbol BTCUSD --side buy --size 1 --type limit_order --limit-price 95000 --i-understand-live
```

---

### Bot & Deployment Management

#### `deployments`
Manage persistent background trading bots.
```bash
# List all active deployments with status and PnL
python -m delta_bt deployments list

# Add a new testnet deployment
python -m delta_bt deployments add --name "BTC Momentum Bot" --venue testnet \
  --strategy supertrend_mom --symbol BTCUSD --resolution 15m --size 0.001 \
  --sl-pct 1.2 --tp-pct 2.4 --trail-pct 0.8

# Add a live production deployment
python -m delta_bt deployments add --name "ETH Live Strategy" --venue live \
  --strategy ema3 --symbol ETHUSD --resolution 15m --size 0.01 --i-understand-live

# Pause, resume, stop, or remove deployment by ID
python -m delta_bt deployments pause 1
python -m delta_bt deployments resume 1
python -m delta_bt deployments stop 1
python -m delta_bt deployments rm 1
```

#### `auto-deploy`
Automatically scan top liquid market gainers, run strategy sweeps, and deploy top-performing bots.
```bash
python -m delta_bt auto-deploy --top 3 --resolution 15m --size 0.001 --testnet
```

#### `bots`, `bot-show`, `bot-events`
Inspect bot fleets and stream activity logs.
```bash
# List running bots
python -m delta_bt bots --all

# Inspect specific bot configuration and recent events
python -m delta_bt bot-show 1 --limit 25

# Stream bot event log history
python -m delta_bt bot-events 1 --kind entry
```

#### `watch`
Run the deployment scheduler loop (executes strategy ticks for all active deployments).
```bash
python -m delta_bt watch --interval 15
```

---

### Terminal Monitoring & Emergency Kill-Switch

#### `monitor`
Launch auto-refreshing live terminal dashboard displaying active bots, positions, mark prices, liquidation prices, and PnL.
```bash
python -m delta_bt monitor --interval 3
```

#### `bot-close-all` (🚨 Emergency Kill-Switch)
Immediately issue market reduce-only orders for **ALL open exchange positions** across Testnet & Live venues.
```bash
python -m delta_bt bot-close-all
```

---

### Portfolio PnL & Performance Analytics

#### `pnl`
Display portfolio summary table, starting capital, win rate %, Sharpe ratio, max drawdown %, fees paid, ASCII equity curve, and daily PnL breakdown.
```bash
python -m delta_bt pnl --days 30
```

#### `pnl-strategy`
View performance and win-rate breakdown grouped per strategy.
```bash
python -m delta_bt pnl-strategy
```

#### `runs`, `run-show`, `trades`
View historical backtest runs stored in SQLite.
```bash
# List stored runs
python -m delta_bt runs --limit 20

# View run details and trade history
python -m delta_bt run-show 1 --limit-trades 50

# List individual trade entries/exits
python -m delta_bt trades --symbol BTCUSD --limit 50
```

#### `compare`, `plot`, `plot-diag`
Compare runs and render equity curve plots.
```bash
# Compare strategy runs in terminal
python -m delta_bt compare --symbol BTCUSD

# Render equity curve PNG chart from SQLite runs
python -m delta_bt plot --last 5 --out ./reports/plots/equity.png --markers

# Render ADX/regime diagnostic chart for a run
python -m delta_bt plot-diag --run-id 1 --out ./reports/plots/diag.png
```

---

### Universe Ranking & Market Scanning

#### `rank-universe`
Rank tradable perpetual contracts across Delta Exchange by liquidity turnover, ADX trend strength, and ATR volatility.
```bash
# Rank top 20 perpetual contracts by liquidity
python -m delta_bt rank-universe --top 20

# Filter universe with trend regime bias
python -m delta_bt rank-universe --regime-bias trend --top 15 --out ./reports/universe/trend.csv

# Filter universe for range/mean-reversion setups
python -m delta_bt rank-universe --regime-bias range --adx-range-max 18 --atr-min-pct 1.0 --atr-max-pct 4.0
```

#### `folio` & `balance`
Inspect wallet balances, collateral usage, and open positions.
```bash
python -m delta_bt folio --venue both
python -m delta_bt balance --venue testnet
```

---

### Background Task Scheduler (`tasks`)

Manage automated 24/7 background jobs (Risk Managers, Scalp Hunters, Circuit Breakers, Reports).
```bash
# List all registered background tasks
python -m delta_bt tasks list

# Trigger a task immediately
python -m delta_bt tasks run-now --id 1

# View execution logs for a background task
python -m delta_bt tasks logs --id 1 --limit 50

# Pause or resume background tasks
python -m delta_bt tasks pause --id 1
python -m delta_bt tasks resume --id 1

# Add custom background task
python -m delta_bt tasks add --name "Emergency Monitor" --script emergency_monitor.py --interval 300
```

---

### Database Maintenance & Utilities

#### `db-info`, `db-path`, `db-vacuum`, `db-clear`
Inspect and optimize the SQLite database.
```bash
# Print resolved database path and row count statistics
python -m delta_bt db-info

# Vacuum and optimize SQLite storage
python -m delta_bt db-vacuum

# Clear table data (e.g. trades, runs, equity)
python -m delta_bt db-clear trades -y
```

#### `serve`
Launch local FastAPI backend server (port 8000) for optional external frontend integration.
```bash
python -m delta_bt serve --host 127.0.0.1 --port 8000
```

---

## 5. Complete Strategies Catalog (30+ Strategies)

Located in `delta_bt/strategies/`:

| Strategy Module | Category | Description | Key Parameters |
|---|---|---|---|
| `ema_cross` | Trend Following | Classic Dual EMA Crossover (Fast / Slow) | `fast=9`, `slow=21` |
| `ema3` | Trend Following | Triple EMA Confluence Strategy | `fast=9`, `mid=21`, `slow=55` |
| `supertrend_mom` | Trend Following | Supertrend Indicator with Momentum Filter | `atr_period=10`, `multiplier=3.0` |
| `supertrend_mom_v2` | Trend Following | Enhanced Multi-timeframe Supertrend | `atr_period=10`, `multiplier=3.0` |
| `macd` | Trend Following | Standard MACD Signal Line Crossover | `fast=12`, `slow=26`, `signal=9` |
| `macd_divergence` | Trend / Reversal | MACD Price-Oscillator Divergence Detector | `fast=12`, `slow=26`, `lookback=30` |
| `ichimoku_cloud` | Trend Following | Ichimoku Kinko Hyo Cloud Breakout | `tenkan=9`, `kijun=26`, `senkou_b=52` |
| `turtle` | Trend Breakout | Classic Donchian Channel Turtle System | `entry_window=20`, `exit_window=10` |
| `momentum_breakout` | Trend Breakout | Price N-Bar High/Low Momentum Breakout | `period=20`, `vol_mult=1.5` |
| `rsi_mr` | Mean Reversion | Relative Strength Index Oversold/Overbought | `period=14`, `oversold=30`, `overbought=70` |
| `rsi_divergence` | Mean Reversion | Regular & Hidden RSI Divergence Detector | `period=14`, `lookback=30` |
| `ema_rsi` | Mean Reversion | EMA Trend-Filtered RSI Strategy | `ema_len=50`, `rsi_len=14` |
| `sma_rsi` | Mean Reversion | Simple Moving Average Filtered RSI | `sma_len=200`, `rsi_len=14` |
| `bollinger` | Volatility | Bollinger Bands Mean Reversion / Breakout | `period=20`, `stdev=2.0`, `mode="revert"` |
| `bb_ha_supertrend` | Confluence | Bollinger Bands + Heikin-Ashi + Supertrend | `bb_len=20`, `atr_len=10`, `mult=3.0` |
| `keltner_squeeze` | Volatility | Keltner Channel Volatility Compression Squeeze | `kc_mult=1.5`, `bb_mult=2.0` |
| `vwap` | Intraday | VWAP Trend & Mean Reversion Strategy | `mode="trend"`, `band_bps=20` |
| `vwap_bands` | Intraday | Standard Deviation VWAP Bands | `stdev_mult=2.0` |
| `price_action_pinbar` | Price Action | Pinbar Wicks & Swing Rejection Strategy | `wick_ratio=2.0`, `body_frac=0.33` |
| `price_action_engulfing`| Price Action | Bullish/Bearish Engulfing Candle Strategy | `min_body_ratio=1.2`, `ema_len=50` |
| `fvg` | SMC | Fair Value Gap Imbalance & Liquidity Fill | `lookback_close=50` |
| `smc_ob` | SMC | Order Block (OB) Impulse Reaction | `impulse_bars=3`, `impulse_mult=1.5` |
| `smc_ob_fvg` | SMC | Order Block + FVG Confluence Entry | `imp_bars=3`, `fvg_lookback=40` |
| `smc_choch_bos` | SMC | Change of Character (CHoCH) & BOS | `swing=5` |
| `smc_bos_retest` | SMC | Break of Structure (BOS) Retest Strategy | `swing=5`, `retest_window=15` |
| `smc_liquidity_sweep` | SMC | Liquidity Sweep & Stop Hunt Reversal | `lookback=20`, `wick_ratio=0.5` |
| `grid` | Grid Trading | Dynamic Sideways Grid Order Matrix | `grid_levels=10`, `spacing_pct=0.5` |
| `options_iron_condor` | Options | Delta Neutral Iron Condor Options Strategy | `delta_target=0.15` |
| `move_volatility_straddle`| Options / Vol | MOVE Contract Volatility Straddle | `vol_threshold=2.0` |

---

## 6. Complete Background Tasks Catalog (60+ Tasks)

Located in `delta_bt/tasks/`:

### 🛡️ Risk Management & Circuit Breakers
* `emergency_monitor.py`: System-wide automated emergency position liquidation guard.
* `volatility_circuit_breaker.py`: Halts bot execution during sudden extreme market volatility.
* `risk_daily_loss_limit.py`: Enforces max daily loss stop-switch across portfolio.
* `risk_max_drawdown_guard.py`: Suspends trading when portfolio drawdown exceeds threshold.
* `risk_funding_rate_guard.py`: Prevents position entry during adverse funding rate spikes.
* `risk_margine_utlisation_guard.py`: Monitors margin utilization to prevent liquidation calls.
* `risk_correlation_limiter.py`: Caps portfolio risk exposure on highly correlated crypto pairs.
* `risk_sector_exposure_cap.py`: Enforces sector diversification limits (L1, DeFi, AI tokens).
* `risk_slippage_monitor.py` & `slippage_tracker.py`: Tracks order execution fill slippage.
* `position_age_monitor.py` & `risk_position_age_timeout.py`: Closes stagnant trade positions after time limits.
* `duplicate_position_guard.py`: Prevents duplicate order placement on identical assets.
* `news_blackout.py`: Pauses trading bots ahead of major economic news events.
* `liquidity_guard.py` & `risk_liquidity_guard.py`: Rejects order entries in illiquid orderbooks.

### 💰 Capital Allocation & Position Sizing
* `atr_position_sizer.py`: Computes volatility-adjusted position sizing using ATR.
* `capital_allocator.py`: Dynamically re-allocates capital to bots based on win rate & Sharpe.
* `rsik_kelly_sizer.py`: Applies Kelly Criterion formula for optimal trade sizing.
* `risk_volatility_regime_sizer.py`: Scales position size according to current volatility regime.
* `anti_correlation_deployer.py`: Selects non-correlated strategy combinations for deployment.

### 🔍 Market Scanners & Strategy Hunters
* `smc_hunter.py`: Scans market perps for Order Block and Fair Value Gap setups.
* `vwap_reversion_hunter.py`: Identifies extreme price deviations from VWAP.
* `scalp_hunter.py`: High-frequency scanner for micro-scalp opportunities.
* `keltner_scanner.py`: Scans for Keltner channel volatility squeeze compressions.
* `funding_arbitrage_farmer.py`: Detects funding rate arbitrage opportunities across perps.
* `liquidation_cascade_hunter.py`: Snipes entries on crypto liquidation cascades.
* `volume_anomaly_sniper.py`: Detects unusual volume surges across Delta pairs.
* `open_interst.py`: Tracks Open Interest (OI) surges and price divergence.
* `fear_greed_monitor.py`: Integrates Crypto Fear & Greed sentiment index.
* `stat_arb_scanner.py`: Statistical arbitrage pair-trading scanner.
* `regim_detector.py`: Classifies market condition into Trending vs Range-bound.
* `strategy_hunter.py` & `auto_deployer`: Auto-discovers and deploys profitable strategies.
* `strategy_retirement.py`: Automatically decommissions underperforming deployment bots.
* `strategy_tuner_task.py` & `hyperparam_auto_tuner.py`: Runs hyperparameter optimizations.
* `session_aware_deployer.py`: Adjusts bot activity according to Asian/London/NY sessions.

### 📊 Analytics, Reports & Maintenance
* `daily_report.py`: Generates daily performance report and Telegram notifications.
* `pnl_attribution.py`: Deconstructs PnL attribution per strategy, timeframe, and asset.
* `api_health_check.py`: Tests API latency and REST/WebSocket connectivity health.
* `best_time_of_the_day.py`: Analyzes historical win-rates by hour of day.
* `correlation_matrix_analyzer.py`: Computes cross-asset price correlation matrices.
* `deployment_snapshot.py`: Takes snapshots of active deployments and equity states.
* `stale_bot_cleaner.py`: Purges inactive or dead bot processes.
* `sb_vacum.py`: Performs SQLite database vacuuming and log pruning.
* `webhook_dispatcher.py`: Dispatches real-time alerts to Telegram/Discord webhooks.

---

## 7. 24/7 Cloud Server Operations

For cloud server hosting (AWS EC2, DigitalOcean, Hetzner, Linux VPS), see **[`CLOUD.md`](./CLOUD.md)**.

### Running 24/7 in `tmux`:
```bash
tmux new -s delta-cli
cd delta-cli
./run.sh
```
*(Press `Ctrl+B` then `D` to detach. Reattach anytime with `tmux attach -t delta-cli`)*

### Systemd Background Service:
Create `/etc/systemd/system/delta-cli.service`:
```ini
[Unit]
Description=Delta CLI Deployment Watcher
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
Enable and start service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable delta-cli
sudo systemctl start delta-cli
sudo systemctl status delta-cli
```

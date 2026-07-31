# Setup Guide — Backtest · Live Bot · Web

Step-by-step walkthrough for running the framework locally. Start with the
Windows PowerShell or macOS/Linux install block below, then continue to
backtest, live bot, and web UI.

Contents: 0. [Install correctly](#0-install-correctly)

1. [Backtest — detailed](#1-backtest--detailed)
2. [Live bot — detailed](#2-live-bot--detailed)
3. [Web interface](#3-web-interface)

---

## 0. Install correctly

### Windows PowerShell

Run these from the project root:

```powershell
cd python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m delta_bt list-strategies
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Important:

- Your prompt should show `(.venv)` before installing packages.
- Use `python -m pip install -r requirements.txt`, not bare `pip install ...`.
- If you already installed before activating and see `ModuleNotFoundError: No module named 'requests'`, activate `.venv` and run `python -m pip install -r requirements.txt` again.
- In PowerShell, `source .venv/bin/activate` is wrong; that is for Bash.
- In PowerShell, `\` is not a line continuation; use a single-line command or a backtick `` ` ``.

### macOS / Linux / Git Bash

```bash
cd python
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m delta_bt list-strategies
```

---

## 1. Backtest — detailed

### 1.1 Pick a strategy

```bash
python -m delta_bt list-strategies
```

You'll see 15+ strategies. Good starting points:

| Strategy              | Style                 | Best timeframe |
| --------------------- | --------------------- | -------------- |
| `ema_cross`           | trend                 | 5m – 1h        |
| `supertrend_mom`      | trend + momentum      | 15m – 1h       |
| `rsi_mr`              | mean-reversion        | 5m – 15m       |
| `bollinger`           | mean-reversion        | 15m – 1h       |
| `smc_bos_retest`      | SMC breakout + retest | 15m – 4h       |
| `smc_ob_fvg`          | SMC confluence        | 15m – 1h       |
| `smc_liquidity_sweep` | SMC reversal          | 5m – 15m       |
| `price_action_pinbar` | price action          | 15m – 4h       |

### 1.2 Run a first backtest

No API keys needed — historical candles are public.

**Windows PowerShell, easiest single-line version:**

```powershell
python -m delta_bt backtest --strategy smc_bos_retest --symbol BTCUSD --timeframe 15m --days 60 --capital 10000 --sl-pct 1.2 --tp-pct 2.4 --trail-pct 0.8 --leverage 3 --params '{"swing":5,"retest_window":15,"buffer_pct":0.1}'
```

**macOS / Linux / Git Bash:**

```bash
python -m delta_bt backtest \
    --strategy smc_bos_retest \
    --symbol BTCUSD \
    --timeframe 15m \
    --days 60 \
    --capital 10000 \
    --sl-pct 1.2 --tp-pct 2.4 --trail-pct 0.8 \
    --leverage 3 \
    --params '{"swing":5,"retest_window":15,"buffer_pct":0.1}'
```

At the end you'll see a printed report with PnL, win-rate, profit factor,
expectancy, max drawdown, Sharpe, and exit-reason breakdown
(`stop_loss / take_profit / trailing_stop / exit`).

### 1.3 Where results go

Every run produces two things:

1. `./reports/<run_id>/` — `trades.csv`, `equity.csv`, `fills.csv`, `summary.json`, `report.txt`
2. A row + trade log inside `python/data/delta_bt.sqlite`

### 1.4 Iterate on parameters

Change `--params`, `--sl-pct`, `--tp-pct`, `--trail-pct`, `--leverage`, or
`--timeframe`, and re-run. Every run is stored, so you can compare.

```bash
python -m delta_bt runs --limit 20
python -m delta_bt compare --symbol BTCUSD
python -m delta_bt plot --last 5 --normalize --markers \
    --out ./reports/plots/compare.png
```

### 1.5 Sanity-check checklist before trusting a strategy

- [ ] At least 60–90 days of history in the window
- [ ] ≥ 30 trades in the sample (otherwise the metrics are noise)
- [ ] Win-rate × avg_win vs (1−win-rate) × avg_loss ⇒ **positive expectancy**
- [ ] Profit factor ≥ 1.3
- [ ] Max drawdown you can actually stomach
- [ ] Fees + slippage set to realistic values (`--fee-bps 5 --slippage-bps 2` is a starting point)
- [ ] Re-run on a **different symbol and different date range** — did it hold?

---

## 2. Live bot — detailed

There are **three** progressively-riskier modes. Do them in order.

```text
paper (sim only)      →   paper --live-orders (testnet)   →   live (production, real money)
      no API keys              testnet API keys                  production API keys
                                + --i-understand flag
```

### 2.1 Create a Delta India testnet account

1. Go to <https://testnet.delta.exchange> and sign up.
2. In the dashboard: **API Management → Create new API key**.
3. Enable **Trading** permission. **Do not** enable withdrawals.
4. Copy the **key** and **secret** — the secret is shown once.
5. (Optional) whitelist your local IP.

### 2.2 Store keys locally

Copy `.env.example` → `.env` inside `python/`:

```dotenv
# demo / testnet
DELTA_BASE_URL=https://cdn-ind.testnet.deltaex.org
DELTA_WS_URL=wss://socket-ind.testnet.deltaex.org
DELTA_API_KEY=your_testnet_key
DELTA_API_SECRET=your_testnet_secret
```

The `.env` is loaded automatically by the CLI. Never commit it. Add to `.gitignore`.

### 2.3 Step 1 — paper (simulated fills, live prices)

Runs the strategy against the live WebSocket price feed but **fills are
simulated locally**. No orders are sent anywhere. Perfect first check.

```bash
python -m delta_bt paper \
    --strategy supertrend_mom \
    --symbol BTCUSD \
    --timeframe 1m \
    --duration 3600 \
    --sl-pct 1.0 --tp-pct 2.0 --trail-pct 0.5 \
    --capital 10000
```

Watch the console. Each bar prints `close`, the signal, and current equity.
If it looks sane after a full session, move on.

### 2.4 Step 2 — paper with real testnet orders

Same command, but adds `--live-orders`. Orders are POST-ed to the **demo**
venue, so they hit the real matching engine but with fake money.

```bash
python -m delta_bt paper \
    --strategy supertrend_mom \
    --symbol BTCUSD \
    --timeframe 1m \
    --live-orders --live-qty 1 \
    --sl-pct 1.0 --tp-pct 2.0 --trail-pct 0.5
```

Check the fills in the testnet dashboard match what the CLI prints. If the
strategy fills, sizes, and cancels behave correctly for a full session,
you're ready for production.

### 2.5 Step 3 — real production live trading

1. Repeat step 2.1 on the **production** exchange at <https://www.delta.exchange>
   → create a **production** API key with **Trading** permission only,
   **withdrawals disabled**, and IP-whitelist your machine.
2. Update `.env`:

   ```dotenv
   DELTA_BASE_URL=https://api.india.delta.exchange
   DELTA_WS_URL=wss://socket.india.delta.exchange
   DELTA_API_KEY=your_production_key
   DELTA_API_SECRET=your_production_secret
   ```

   (Or leave `.env` on testnet and pass `--base-url` / `--ws-url` / `--api-key`
   / `--api-secret` explicitly on the CLI so you can't confuse envs.)

3. Start with the **smallest possible quantity** (`--live-qty 1`) and the
   safety flag:

   ```bash
   python -m delta_bt live \
       --strategy supertrend_mom \
       --symbol BTCUSD \
       --timeframe 5m \
       --live-qty 1 \
       --sl-pct 1.0 --tp-pct 2.0 --trail-pct 0.5 \
       --i-understand
   ```

   Without `--i-understand` the CLI refuses to start.

### 2.6 Running the bot 24/7

Two easy options — pick one:

- **tmux / screen** (simplest):

  ```bash
  tmux new -s bot
  source .venv/bin/activate
  python -m delta_bt live --strategy ema3 --symbol BTCUSD \
      --timeframe 5m --live-qty 1 --i-understand
  # Ctrl-B then D to detach; `tmux attach -t bot` to come back
  ```

- **systemd unit** (`/etc/systemd/system/delta-bot.service`):

  ```ini
  [Unit]
  Description=Delta India live bot
  After=network-online.target

  [Service]
  Type=simple
  WorkingDirectory=/home/you/delta_bt/python
  EnvironmentFile=/home/you/delta_bt/python/.env
  ExecStart=/home/you/delta_bt/python/.venv/bin/python -m delta_bt live \
      --strategy ema3 --symbol BTCUSD --timeframe 5m \
      --live-qty 1 --i-understand
  Restart=on-failure
  RestartSec=10

  [Install]
  WantedBy=multi-user.target
  ```

  Then `sudo systemctl enable --now delta-bot` and `journalctl -u delta-bot -f`
  to tail logs.

### 2.7 Kill switches & safety

- **Ctrl-C** in the terminal stops the bot cleanly and force-closes any open position on the last bar.
- **Exchange-side**: from the Delta dashboard you can cancel all open orders and close positions manually at any time.
- **Rotate keys** if you suspect exposure: Delta dashboard → API Management → revoke.
- Every live run is stored in SQLite — audit later with `python -m delta_bt runs`.

---

## 3. Web interface

The project now includes two UI options:

1. The TanStack Start UI in the repo root.
2. A standalone **Next.js 15 + Tailwind v4 + Radix UI** dashboard in `web/`.

Both read from the same local FastAPI backend and SQLite run database.

### 3.1 Start the Python backend

Open terminal 1:

```powershell
cd python
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m delta_bt serve
```

Backend URL: `http://127.0.0.1:8000`

### 3.2 Start the standalone Next.js UI

Open terminal 2 from the project root:

```powershell
cd web
npm install
npm run dev
```

Next.js URL: `http://localhost:3001`

### 3.3 What the web UI shows

- `/runs` — browse stored backtest / paper / live runs
- `/runs/[id]` — open metrics, equity plot, and heatmap plot
- `/compare` — compare PnL/equity, select Top 5 by return, clear selection, and view summary stats

The same data is still accessible from the CLI:

```bash
python -m delta_bt runs
python -m delta_bt compare
python -m delta_bt plot --last 5 --markers --out ./reports/plots/x.png
sqlite3 python/data/delta_bt.sqlite "SELECT * FROM runs ORDER BY created_at DESC LIMIT 10;"
```

Design constraint: local-only, no auth, no cloud, uses the same SQLite file the CLI writes to — CLI and Web stay 100% interchangeable.

Confirm you want this and I'll create it in one pass.

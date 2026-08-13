#!/bin/bash
# Minimal daily strategy list — running/dead, no PnL.
cd /root/delta-cli || exit 1
strip_ansi() { sed -e 's/\x1b\[[0-9;]*m//g'; }

echo "📋 **STRATEGIES** — $(date -u '+%Y-%m-%d %H:%M UTC')"

# Delta-MCP standalone strategies (process check)
chk() { ps aux | grep -v grep | grep -q "$2" && echo "✅ $1" || echo "❌ $1"; }
chk "EMA crossover"  "ema_crossover_strategy.py"
chk "RSI mean-rev"   "rsi_mean_reversion_strategy.py"
chk "Momentum"       "python_strategy_runner.py"
chk "LLM agent"      "local_hermes_trading_agent.py"

# delta-cli fleet
T=$(venv/bin/python -m delta_bt tasks list 2>/dev/null | strip_ansi | grep -E '^ *[0-9]+ {2,}')
echo "⚙️ delta-cli tasks: $(echo "$T" | grep -c ' running ') running / $(echo "$T" | grep -c ' paused ') paused"
D=$(venv/bin/python -m delta_bt deployments list 2>/dev/null | strip_ansi | grep ' live ' | grep ' running ' | sed -E 's/^ *[0-9]+ +//; s/ {2,}.*//' | paste -sd ',' | sed 's/,/, /g')
echo "🚀 Live deploys: ${D:-none}"

#!/bin/bash

# Activate the virtual environment
source venv/bin/activate

echo "🚀 Starting backtest for Supertrend Momentum strategy..."

# Run the backtest using delta_bt CLI
python -m delta_bt backtest \
  --strategy supertrend_mom \
  --symbol BTCUSD \
  --resolution 5m \
  --start "2026-07-20T00:00:00Z" \
  --end "2026-07-31T00:00:00Z"

echo "✅ Backtest complete! Check the 'reports' folder for the generated CSVs and summary."

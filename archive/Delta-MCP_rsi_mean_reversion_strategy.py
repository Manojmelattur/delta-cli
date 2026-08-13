"""
=============================================================================
Strategy 3: RSI Mean Reversion Strategy for Delta Exchange
=============================================================================
Uses 14-period RSI (Relative Strength Index) to detect oversold support 
bounces (RSI < 30) and overbought reversals (RSI > 70) for range-bound trading.
=============================================================================
"""

import sys
import os
import time
import asyncio
import logging

sys.path.insert(0, r"C:\Users\HP\AppData\Roaming\Python\Python314\site-packages")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from delta_exchange_mcp.config import load
from delta_exchange_mcp.client import DeltaClient

# Setup logging
log_file = os.path.join(os.path.dirname(__file__), "rsi_strategy_log.md")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [RSI STRATEGY] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)

DELTA_MCP_ENV = os.environ.get("DELTA_MCP_ENV", "india_prod")
os.environ["DELTA_MCP_ENV"] = DELTA_MCP_ENV
os.environ["DELTA_API_KEY"] = os.environ.get("DELTA_API_KEY", "")
os.environ["DELTA_API_SECRET"] = os.environ.get("DELTA_API_SECRET", "")
os.environ["DELTA_MCP_MODE"] = "trade"

# SAFETY: never place orders unless TRADE_LIVE=true. Default = dry-run.
TRADE_LIVE = os.environ.get("TRADE_LIVE", "false").lower() in ("1", "true", "yes")
if not TRADE_LIVE:
    os.environ["DELTA_MCP_MODE"] = "read"

# Drawdown kill-switch
MAX_DRAWDOWN_PCT = 15.0
# MINIMAL-START risk rule: keep each trade tiny on this small account.
MINIMAL_RISK_PERCENT = 0.02
MAX_TRADE_NOTIONAL_USD = 5.0

import json as _json
def _load_my_symbols(strategy_key):
    try:
        with open(os.path.join(os.path.dirname(__file__), "coin_assignments.json")) as f:
            return _json.load(f)["strategies"].get(strategy_key, [])
    except Exception:
        return []

cfg = load()

MAX_LEVERAGE = 5.0
RISK_PERCENT = 0.10
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

async def run_rsi_strategy():
    mode = "LIVE (orders enabled)" if TRADE_LIVE else "DRY-RUN (analysis only, NO orders)"
    logging.info("======================================================================")
    logging.info("🚀 Starting 14-Period RSI Mean Reversion Strategy Engine")
    logging.info(f"🔒 MODE: {mode}")
    logging.info("======================================================================")

    symbols_to_monitor = _load_my_symbols("rsi_mean_reversion") or ["SOLUSD", "XRPUSD"]
    session_start_equity = None

    while True:
        client = DeltaClient(cfg)
        try:
            # 1. Audit Balance
            bal = await client.get('/wallet/balances', auth=True)
            usd_bal = [b for b in bal.get('result', []) if b.get('asset_symbol') == 'USD'][0]
            avail_margin = float(usd_bal.get('available_balance', 0))
            equity = float(usd_bal.get('balance', 0))
            if session_start_equity is None:
                session_start_equity = equity
            dd_pct = (session_start_equity - equity) / session_start_equity * 100 if session_start_equity else 0
            if dd_pct > MAX_DRAWDOWN_PCT:
                logging.error(f"🛑 MAX DRAWDOWN {dd_pct:.1f}% exceeded — HALTING engine. Restart manually after review.")
                return
            logging.info(f"💰 Available Margin: ${avail_margin:.2f} USD | Drawdown: {dd_pct:.1f}%")

            # 2. Check Open Positions
            pos = await client.get('/positions/margined', auth=True)
            open_pos = pos.get('result', [])
            logging.info(f"📊 Active Positions: {len(open_pos)}")

            # 3. Analyze Candles for RSI Signals
            for symbol in symbols_to_monitor:
                try:
                    now = int(time.time())
                    start = now - (30 * 15 * 60)
                    candles_resp = await client.get(f'/chart/history?symbol={symbol}&resolution=15&from={start}&to={now}')
                    candles = candles_resp.get('result', [])
                    
                    if len(candles) >= 15:
                        close_prices = [float(c['close']) for c in candles]
                        rsi = calculate_rsi(close_prices, 14)
                        current_price = close_prices[-1]
                        
                        logging.info(f"📉 {symbol} | Price: ${current_price:.2f} | 14 RSI: {rsi:.1f}")

                        # BUY Signal: Oversold Bounce (RSI < 30)
                        if rsi < RSI_OVERSOLD and avail_margin > 5.0 and len(open_pos) == 0:
                            logging.info(f"🎯 OVERSOLD SIGNAL DETECTED ON {symbol}! (RSI = {rsi:.1f} < 30)")
                            lot_size = max(1, int((avail_margin * MINIMAL_RISK_PERCENT * MAX_LEVERAGE) / current_price))
                            # hard notional cap so no single trade can blow up the small account
                            max_lots = int(MAX_TRADE_NOTIONAL_USD / max(0.0001, current_price))
                            lot_size = min(lot_size, max(1, max_lots))
                            
                            order_payload = {
                                "product_symbol": symbol,
                                "size": lot_size,
                                "side": "buy",
                                "order_type": "market_order",
                                "client_order_id": f"rsi_{int(time.time())}",
                                "bracket_orders": [
                                    {"order_type": "stop_loss_order", "stop_price": str(round(current_price * 0.97, 4)), "stop_loss_price": str(round(current_price * 0.97, 4))},
                                    {"order_type": "take_profit_order", "stop_price": str(round(current_price * 1.05, 4)), "take_profit_price": str(round(current_price * 1.05, 4))}
                                ]
                            }
                            res = await client.post('/orders', data=order_payload, auth=True)
                            logging.info(f"✅ RSI Order Executed for {symbol}: {res.get('result', {}).get('id')}") if TRADE_LIVE else logging.info(f"🔍 Dry-run: would BUY {symbol} | Lots: {lot_size} | Lev: {MAX_LEVERAGE}x (set TRADE_LIVE=true to enable).")

                except Exception as sym_err:
                    logging.error(f"Error checking RSI for {symbol}: {sym_err}")

        except Exception as e:
            logging.error(f"⚠️ Engine Error: {e}")
        finally:
            await client.aclose()

        await asyncio.sleep(90)

if __name__ == "__main__":
    try:
        asyncio.run(run_rsi_strategy())
    except KeyboardInterrupt:
        print("\n🛑 RSI Strategy Engine stopped by user.")

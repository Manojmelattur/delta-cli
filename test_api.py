import requests

res = requests.post("http://127.0.0.1:8000/api/deployments/create", json={
    "name": "test1234",
    "venue": "paper",
    "strategy": "time_breakout",
    "symbol": "BTC-USDT",
    "timeframe": "15m",
    "lot": 1.0,
    "sl_pct": 0.0,
    "tp_pct": 0.0,
    "trail_pct": 0.0,
    "params": {}
})
print("Deployment:", res.status_code, res.text)

res2 = requests.post("http://127.0.0.1:8000/api/backtest", json={
    "strategy": "time_breakout",
    "symbol": "BTC-USDT",
    "timeframe": "15m",
    "days": 30,
    "capital": 1000,
    "fee_bps": 5,
    "slippage_bps": 2,
    "leverage": 1,
    "qty_pct": 1.0,
    "sl_pct": 0.0,
    "tp_pct": 0.0,
    "trail_pct": 0.0,
    "live": False,
    "params": {}
})
print("Backtest:", res2.status_code, res2.text)

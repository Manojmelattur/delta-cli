import urllib.request
import json
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/deployments/create",
    data=json.dumps({
        "name": "test_bot_99",
        "venue": "paper",
        "strategy": "time_breakout",
        "symbol": "BTC-USDT",
        "timeframe": "15m",
        "lot": 1.0,
        "sl_pct": 0.0,
        "tp_pct": 0.0,
        "trail_pct": 0.0,
        "params": {}
    }).encode('utf-8'),
    headers={"Content-Type": "application/json"}
)
try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(f"Error {e.code}: {e.read().decode('utf-8')}")

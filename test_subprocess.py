import subprocess
import json

req = {
    "strategy": "time_breakout",
    "symbol": "BTC-USDT",
    "timeframe": "15m",
    "days": 30,
    "capital": 1000,
    "fee_bps": 5,
    "slippage_bps": 2,
    "qty_pct": 1,
    "leverage": 1,
    "sl_pct": 0,
    "tp_pct": 0,
    "trail_pct": 0,
    "live": False,
    "params": {}
}

cmd = [
    "python", "-m", "delta_bt", "backtest",
    "--strategy", req["strategy"],
    "--symbol", req["symbol"],
    "--timeframe", req["timeframe"],
    "--days", str(req["days"]),
    "--capital", str(req["capital"]),
    "--fee-bps", str(req["fee_bps"]),
    "--slippage-bps", str(req["slippage_bps"]),
    "--qty-pct", str(req["qty_pct"]),
    "--leverage", str(req["leverage"]),
    "--sl-pct", str(req["sl_pct"]),
    "--tp-pct", str(req["tp_pct"]),
    "--trail-pct", str(req["trail_pct"]),
    "--params", json.dumps(req["params"])
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("Return code:", res.returncode)
print("Stdout:", res.stdout)
print("Stderr:", res.stderr)

from fastapi import FastAPI
import subprocess
import json
import os

def add_pnl_routes(app: FastAPI):
    @app.get("/api/pnl/summary")
    def get_pnl_summary(days: int = 30, venue: str = None, strategy: str = None, symbol: str = None):
        cmd = ["python", "-m", "delta_bt", "pnl", "--days", str(days), "--json"]
        if venue: cmd.extend(["--venue", venue])
        if strategy: cmd.extend(["--strategy", strategy])
        if symbol: cmd.extend(["--symbol", symbol])
        
        try:
            # We need to run this in the parent directory
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                return {"error": res.stderr}
            return json.loads(res.stdout)
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/pnl/strategy")
    def get_pnl_strategy(days: int = 30, venue: str = None, symbol: str = None):
        cmd = ["python", "-m", "delta_bt", "pnl-strategy", "--days", str(days), "--json"]
        if venue: cmd.extend(["--venue", venue])
        if symbol: cmd.extend(["--symbol", symbol])
        
        try:
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                return {"error": res.stderr}
            return json.loads(res.stdout)
        except Exception as e:
            return {"error": str(e)}

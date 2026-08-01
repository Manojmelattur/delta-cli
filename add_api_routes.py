with open("delta_bt/server.py", "r") as f:
    content = f.read()

new_routes = """
    from pydantic import BaseModel
    
    class BacktestRequest(BaseModel):
        strategy: str
        symbol: str
        timeframe: str = "15m"
        days: int = 30
        capital: float = 10000.0
        
    class ScanRequest(BaseModel):
        strategy: Optional[str] = None
        symbol: Optional[str] = None
        timeframe: str = "15m"
        top: int = 10
        
    class DeployRequest(BaseModel):
        name: str
        venue: str = "paper"
        strategy: str
        symbol: str
        timeframe: str = "15m"
        lot: float = 1.0

    @app.post("/api/backtest")
    def api_backtest(req: BacktestRequest):
        import subprocess
        import json
        try:
            cmd = [
                "python", "-m", "delta_bt", "backtest",
                "--strategy", req.strategy,
                "--symbol", req.symbol,
                "--timeframe", req.timeframe,
                "--days", str(req.days),
                "--capital", str(req.capital),
                "--save"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "logs": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    @app.post("/api/scan")
    def api_scan(req: ScanRequest):
        import subprocess
        try:
            cmd = ["python", "-m", "delta_bt", "scan", "--timeframe", req.timeframe]
            if req.strategy:
                cmd.extend(["--strategy", req.strategy])
            if req.symbol:
                cmd.extend(["--symbol", req.symbol])
            if req.top:
                cmd.extend(["--top", str(req.top)])
                
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))
            
    @app.post("/api/deployments/create")
    def api_deployments_create(req: DeployRequest):
        import subprocess
        try:
            cmd = [
                "python", "-m", "delta_bt", "deployments", "add",
                "--name", req.name,
                "--venue", req.venue,
                "--strategy", req.strategy,
                "--symbol", req.symbol,
                "--timeframe", req.timeframe,
                "--lot", str(req.lot),
                "--i-understand"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

"""
content = content.replace("    return app", new_routes + "    return app")
with open("delta_bt/server.py", "w") as f:
    f.write(content)

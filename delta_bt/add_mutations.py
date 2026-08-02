from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
import subprocess
import json
import os
import sqlite3

def add_mutations(app: FastAPI, db_path: str):
    
    @app.post("/api/deployments/{dep_id}/edit")
    async def api_edit_deployment(dep_id: str, req: Request):
        try:
            data = await req.json()
            conn = sqlite3.connect(db_path)
            
            if "params" in data:
                # New format with risk fields
                params_str = json.dumps(data.get("params", {}))
                
                def safe_float(val, default=0.0):
                    if val is None:
                        return default
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        return default
                        
                size = safe_float(data.get("size"), 1.0)
                sl_pct = safe_float(data.get("sl_pct"), 0.0)
                tp_pct = safe_float(data.get("tp_pct"), 0.0)
                trail_pct = safe_float(data.get("trail_pct"), 0.0)
                
                cur = conn.execute("""
                    UPDATE deployments 
                    SET params_json=?, size=?, sl_pct=?, tp_pct=?, trail_pct=?
                    WHERE id=?
                """, (params_str, size, sl_pct, tp_pct, trail_pct, dep_id))
            else:
                # Backward compatibility (only params dict)
                params_str = json.dumps(data)
                cur = conn.execute("UPDATE deployments SET params_json=? WHERE id=?", (params_str, dep_id))
                
            conn.commit()
            
            if cur.rowcount == 0:
                raise HTTPException(404, "Deployment not found")
            return {"ok": True}
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(500, detail=str(e))
            
    @app.post("/api/deployments/{dep_id}/test_trade")
    def api_test_trade(dep_id: str):
        try:
            # We first need to get the symbol for the deployment to use with the order command
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            dep = conn.execute("SELECT symbol, venue FROM deployments WHERE id=?", (dep_id,)).fetchone()
            if not dep:
                raise HTTPException(404, "Deployment not found")
                
            cmd = ["python", "-m", "delta_bt", "order", "--symbol", dep["symbol"], "--side", "BUY", "--type", "MARKET"]
            if dep["venue"] == "paper":
                cmd.append("--paper")
                
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
                
            # Log the test trade event to deployment_events
            conn.execute("INSERT INTO deployment_events(deployment_id, event_type, message, level) VALUES(?, ?, ?, ?)",
                         (dep_id, "TEST_TRADE", f"UI Triggered Test Trade: {res.stdout}", "info"))
            conn.commit()
            
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))
            

            
    @app.get("/api/settings")
    def api_get_settings():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT key, value_json FROM app_settings").fetchall()
            return {r["key"]: json.loads(r["value_json"]) for r in rows}
        except Exception as e:
            raise HTTPException(500, detail=str(e))
            
    @app.post("/api/settings")
    async def api_update_settings(req: Request):
        try:
            data = await req.json()
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            for key, val in data.items():
                cur.execute("INSERT OR REPLACE INTO app_settings(key, value_json) VALUES(?, ?)", (key, json.dumps(val)))
            conn.commit()
            return {"ok": True}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    @app.get("/api/system/ip")
    def api_system_ip():
        import requests
        import time
        from email.utils import parsedate_to_datetime
        
        ip_info = {
            "ip": "Unknown",
            "server_date": "Unknown",
            "local_timestamp": 0,
            "skew": 0,
            "skew_status": "UNKNOWN",
            "error": None
        }
        try:
            ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
            ip_info["ip"] = ip
        except Exception as e:
            ip_info["error"] = f"IP check failed: {str(e)}"
            
        try:
            local_before = int(time.time())
            resp = requests.get("https://cdn-ind.testnet.deltaex.org/v2/products?page_size=1", timeout=5)
            server_date = resp.headers.get("Date", "")
            ip_info["server_date"] = server_date
            ip_info["local_timestamp"] = local_before
            
            if server_date:
                server_dt = parsedate_to_datetime(server_date)
                server_ts = int(server_dt.timestamp())
                skew = local_before - server_ts
                ip_info["skew"] = skew
                ip_info["skew_status"] = "PROBLEM" if abs(skew) > 5 else "OK"
        except Exception as e:
            if ip_info["error"]:
                ip_info["error"] += f" | Skew check failed: {str(e)}"
            else:
                ip_info["error"] = f"Skew check failed: {str(e)}"
        return ip_info

    @app.post("/api/system/clear-backtests")
    def api_clear_backtests():
        try:
            conn = sqlite3.connect(db_path)
            for t in ["runs", "trades", "equity", "fills", "diag"]:
                try:
                    conn.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            conn.commit()
            return {"ok": True, "message": "Backtest data cleared successfully"}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    @app.post("/api/system/clear-deployments")
    def api_clear_deployments():
        try:
            conn = sqlite3.connect(db_path)
            for t in ["deployments", "deployment_events", "pending_deployments", "paper_accounts", "paper_orders", "paper_positions", "paper_fills"]:
                try:
                    conn.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            conn.commit()
            return {"ok": True, "message": "Deployments cleared successfully"}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    @app.post("/api/system/seed-default-tasks")
    def api_seed_default_tasks():
        try:
            import sys
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            import reset_tasks
            reset_tasks.run()
            return {"ok": True, "message": "Tasks re-seeded successfully"}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    @app.post("/api/system/factory-reset")
    def api_factory_reset():
        try:
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cmd = ["python", "-m", "delta_bt", "factory-reset", "-y"]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    class AutoDeployRequest(BaseModel):
        venue: str = "paper"
        live: bool = False
        top: int = 10
        days: int = 30
        resolution: str = "1h"
        size: float = 1.0
        sl_pct: float = 1.2
        tp_pct: float = 2.4
        trail_pct: float = 0.8
        symbol: Optional[str] = None

    @app.post("/api/system/auto-deploy")
    def api_auto_deploy(req: AutoDeployRequest):
        try:
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cmd = [
                sys.executable, "-m", "delta_bt", "auto-deploy",
                "--venue", req.venue,
                "--top", str(req.top),
                "--days", str(req.days),
                "--resolution", req.resolution,
                "--size", str(req.size),
                "--sl-pct", str(req.sl_pct),
                "--tp-pct", str(req.tp_pct),
                "--trail-pct", str(req.trail_pct)
            ]
            if req.live:
                cmd.append("--live")
            if req.symbol:
                cmd.extend(["--symbol", req.symbol])
            
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    class RankUniverseRequest(BaseModel):
        top: int = 15
        live: bool = False
        resolution: str = "1h"
        days: int = 30

    @app.post("/api/system/rank-universe")
    def api_rank_universe(req: RankUniverseRequest):
        try:
            import csv as csv_mod
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            csv_path = os.path.join(cwd, "reports", "universe", "universe.csv")
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            cmd = [
                sys.executable, "-m", "delta_bt", "rank-universe",
                "--top", str(req.top),
                "--lookback-bars", str(max(24, req.days * 24)),
                "--timeframe", req.resolution,
                "--out", csv_path
            ]
            if req.live:
                cmd.append("--live")
            
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr or res.stdout)
            
            results = []
            if os.path.exists(csv_path):
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv_mod.DictReader(f)
                    for row in reader:
                        if not row.get("symbol"):
                            continue
                        results.append({
                            "rank": int(row.get("rank", 0)) if row.get("rank") else 0,
                            "symbol": row.get("symbol", ""),
                            "score": float(row.get("score", 0.0)) if row.get("score") else 0.0,
                            "regime": row.get("regime", "unknown"),
                            "price": float(row.get("price", 0.0)) if row.get("price") else 0.0,
                            "turnover_usd": float(row.get("turnover_usd", 0.0)) if row.get("turnover_usd") else 0.0,
                            "open_interest": float(row.get("open_interest", 0.0)) if row.get("open_interest") else 0.0,
                            "funding_pct": float(row.get("funding_pct", 0.0)) if row.get("funding_pct") else 0.0,
                            "adx": float(row.get("adx", 0.0)) if row.get("adx") else 0.0,
                            "atr_pct": float(row.get("atr_pct", 0.0)) if row.get("atr_pct") else 0.0,
                            "bb_width_pct": float(row.get("bb_width_pct", 0.0)) if row.get("bb_width_pct") else 0.0,
                            "ret_pct": float(row.get("ret_pct", 0.0)) if row.get("ret_pct") else 0.0,
                            "rs_vs_btc": float(row.get("rs_vs_btc", 0.0)) if row.get("rs_vs_btc") else 0.0,
                            "reason": row.get("reason", "")
                        })
            return {"ok": True, "results": results, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    class SweepRequest(BaseModel):
        symbol: str = "BTCUSD"
        resolution: str = "15m"
        days: int = 30
        live: bool = False
        sl_pct: float = 0.0
        tp_pct: float = 0.0
        trail_pct: float = 0.0

    @app.post("/api/system/sweep")
    def api_sweep(req: SweepRequest):
        try:
            import csv as csv_mod
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            csv_path = os.path.join(cwd, "reports", "temp_sweep.csv")
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            
            cmd = [
                sys.executable, "-m", "delta_bt", "sweep",
                "--symbol", req.symbol,
                "--resolution", req.resolution,
                "--days", str(req.days),
                "--sl-pct", str(req.sl_pct),
                "--tp-pct", str(req.tp_pct),
                "--trail-pct", str(req.trail_pct),
                "--csv", csv_path
            ]
            if req.live:
                cmd.append("--live")
            # no --testnet flag: sweep uses --live or defaults to cached/demo data
            
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr or res.stdout)
            
            results = []
            if os.path.exists(csv_path):
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv_mod.DictReader(f)
                    for row in reader:
                        if not row.get("strategy"):
                            continue
                        results.append({
                            "strategy": row.get("strategy", ""),
                            "pnl": float(row.get("pnl", 0.0)) if row.get("pnl") else 0.0,
                            "return_pct": float(row.get("return_pct", 0.0)) if row.get("return_pct") else 0.0,
                            "sharpe": float(row.get("sharpe", 0.0)) if row.get("sharpe") else 0.0,
                            "win_rate_pct": float(row.get("winrate", 0.0)) if row.get("winrate") else 0.0,
                            "max_drawdown_pct": float(row.get("dd", 0.0)) if row.get("dd") else 0.0,
                            "trades": int(row.get("trades", 0)) if row.get("trades") else 0,
                            "profit_factor": float(row.get("pf", 0.0)) if row.get("pf") else 0.0
                        })
            return {"ok": True, "results": results, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

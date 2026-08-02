from fastapi import FastAPI, Request, HTTPException
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

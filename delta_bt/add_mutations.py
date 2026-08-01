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
            # delta_bt deployments edit <id> --params '{"size": 2.0}'
            cmd = ["python", "-m", "delta_bt", "deployments", "edit", str(dep_id), "--params", json.dumps(data)]
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
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
            
    @app.post("/api/tasks/{task_name}/edit")
    async def api_edit_task(task_name: str, req: Request):
        try:
            data = await req.json()
            cmd = ["python", "-m", "delta_bt", "tasks", "edit", task_name, "--params", json.dumps(data)]
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))
            
    @app.post("/api/tasks/{task_name}/delete")
    def api_delete_task(task_name: str):
        try:
            cmd = ["python", "-m", "delta_bt", "tasks", "rm", task_name]
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
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

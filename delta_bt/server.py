"""FastAPI web server exposing stored runs to the TanStack UI.

Run:
    python -m delta_bt serve --host 127.0.0.1 --port 8000

Endpoints (all under /api):
    GET  /api/health
    GET  /api/runs?limit=&strategy=&symbol=
    GET  /api/runs/{run_id}
    GET  /api/runs/{run_id}/equity        -> JSON [{ts, equity}]
    GET  /api/runs/{run_id}/trades        -> JSON [...]
    GET  /api/runs/{run_id}/equity.png?markers=1
    GET  /api/runs/{run_id}/heatmap.png   -> monthly PnL heatmap
    GET  /api/compare/equity?ids=a,b&normalize=1
    GET  /api/compare/strategies?symbol=
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from typing import List, Optional


try:
    from fastapi import Request  # module-scope so annotations resolve under `from __future__ import annotations`
except ImportError:  # pragma: no cover
    Request = None  # type: ignore

from .store.db import (
    connect, list_runs, compare_strategies, get_run, get_fills,
    db_info, vacuum_db, clear_table, schema_info,
)
from .deployments import scheduler_status, request_scheduler_restart, scheduler_logs_tail
from .store.plot import plot_runs, _load_equity, _load_trades
from .cache import get_cache



class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    timeframe: str = "15m"
    days: Optional[int] = 30
    start: Optional[str] = None
    end: Optional[str] = None
    capital: float = 10000.0
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    qty_pct: float = 1.0
    leverage: float = 1.0
    sl_pct: float = 0.0
    tp_pct: float = 0.0
    trail_pct: float = 0.0
    live: bool = False
    params: dict = {}
    
class ScanRequest(BaseModel):
    strategy: Optional[str] = None
    symbol: Optional[str] = None
    timeframe: str = "15m"
    top: int = 10
    days: int = 30
    capital: float = 10000.0
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    qty_pct: float = 1.0
    leverage: float = 1.0
    sl_pct: float = 1.2
    tp_pct: float = 2.4
    trail_pct: float = 0.8
    sort_by: str = "pnl"
    min_trades: int = 1
    profitable_only: bool = False
    save: bool = False
    live: bool = False
    json_output: bool = False
    adx_len: int = 14
    adx_trend_min: int = 25
    adx_range_max: int = 20
    adx_exit_on_flip: bool = False
    adx_tighten_trail_on_flip: bool = False

class TaskRequest(BaseModel):
    name: str
    script: str
    interval: int = 900
    desc: str = ""
    params: dict = {}
    
class DeployRequest(BaseModel):
    name: str
    venue: str = "paper"
    strategy: str
    symbol: str
    timeframe: str = "15m"
    lot: Optional[float] = 1.0
    sl_pct: Optional[float] = 0.0
    tp_pct: Optional[float] = 0.0
    trail_pct: Optional[float] = 0.0
    params: dict = {}


def create_app(db_path: Optional[str] = None):
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import Response
    except ImportError as e:
        raise SystemExit(
            "fastapi/uvicorn not installed. Run: pip install fastapi uvicorn"
        ) from e


    app = FastAPI(title="delta_bt web", version="0.1")
    from .add_pnl_routes import add_pnl_routes
    add_pnl_routes(app)
    from .add_mutations import add_mutations
    from .store.db import _resolve_db
    add_mutations(app, str(_resolve_db(db_path)))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"ok": True, "db": db_path or os.getenv("DELTA_BT_DB") or "default"}

    @app.get("/api/redis/health")
    def redis_health():
        cache = get_cache()
        return cache.status()

    @app.get("/api/strategies")
    def api_strategies():
        from .core.registry import discover_strategies
        return list(discover_strategies().keys())

    @app.get("/api/strategies/manifest")
    def api_strategies_manifest():
        try:
            cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            manifest_path = os.path.join(cwd, "strategy_manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r") as f:
                    import json
                    return json.load(f)
            return {"error": "Manifest file not found"}
        except Exception as e:
            return {"error": str(e)}

    # Cache to prevent rate limiting
    symbols_cache = []
    
    @app.get("/api/symbols")
    def api_symbols():
        nonlocal symbols_cache
        if not symbols_cache:
            try:
                import requests
                res = requests.get('https://api.delta.exchange/v2/products', timeout=5)
                if res.status_code == 200:
                    data = res.json().get('result', [])
                    symbols_cache = [p['symbol'] for p in data if p.get('state') != 'expired']
            except Exception as e:
                print(f"Error fetching symbols from Delta Exchange: {e}")
        
        if symbols_cache:
            return symbols_cache
            
        return ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD", "AVAXUSD", "DOGEUSD", "DOTUSD", "LINKUSD", "MATICUSD", "BNBUSD"]

    @app.get("/api/runs")
    def api_runs(limit: int = 100, strategy: Optional[str] = None,
                 symbol: Optional[str] = None):
        return list_runs(limit=limit, strategy=strategy, symbol=symbol,
                         db_path=db_path)

    @app.get("/api/runs/{run_id}")
    def api_run(run_id: str):
        r = get_run(run_id, db_path=db_path)
        if not r:
            raise HTTPException(404, "run not found")
        return r

    @app.get("/api/runs/{run_id}/equity")
    def api_equity(run_id: str):
        ts, eq, _meta = _load_equity(run_id, db_path)
        return [{"ts": t.isoformat(), "equity": v} for t, v in zip(ts, eq)]

    @app.get("/api/runs/{run_id}/trades")
    def api_trades(run_id: str):
        with connect(db_path) as conn:
            cur = conn.execute(
                "SELECT seq, side, qty, entry_ts, entry_price, exit_ts, "
                "exit_price, pnl, fees, return_pct FROM trades "
                "WHERE run_id=? ORDER BY seq", (run_id,))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    @app.get("/api/runs/{run_id}/equity.png")
    def api_equity_png(run_id: str, markers: int = 1, normalize: int = 0):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            out = f.name
        try:
            plot_runs([run_id], out, db_path=db_path,
                      normalize=bool(normalize), markers=bool(markers))
            data = open(out, "rb").read()
        finally:
            try: os.unlink(out)
            except OSError: pass
        return Response(content=data, media_type="image/png")

    @app.get("/api/runs/{run_id}/heatmap.png")
    def api_heatmap_png(run_id: str):
        return Response(content=_render_heatmap(run_id, db_path),
                        media_type="image/png")

    @app.get("/api/compare/equity")
    def api_compare_equity(ids: str = Query(...), normalize: int = 1):
        run_ids = [x for x in ids.split(",") if x]
        out = []
        for rid in run_ids:
            ts, eq, meta = _load_equity(rid, db_path)
            if not eq: continue
            y = eq
            if normalize and eq[0]:
                y = [v / eq[0] * 100.0 for v in eq]
            label = rid
            if meta:
                label = f"{meta[0]} · {meta[1]} {meta[2]}"
            out.append({
                "run_id": rid, "label": label,
                "points": [{"ts": t.isoformat(), "y": v}
                           for t, v in zip(ts, y)],
            })
        return out

    @app.get("/api/compare/strategies")
    def api_compare_strategies(symbol: Optional[str] = None):
        return compare_strategies(symbol=symbol, db_path=db_path)

    @app.get("/api/runs/{run_id}/fills")
    def api_run_fills(run_id: str):
        return get_fills(run_id, db_path=db_path)

    @app.get("/api/runs/{run_id}/summary")
    def api_run_summary(run_id: str):
        r = get_run(run_id, db_path=db_path)
        if not r:
            raise HTTPException(404, "run not found")
        # Strip large payloads; return just the metadata + parsed summary_json.
        import json as _json
        summ = {}
        try:
            summ = _json.loads(r.get("summary_json") or "{}")
        except Exception:
            summ = {}
        r.pop("summary_json", None); r.pop("trades", None); r.pop("equity", None)
        r["summary"] = summ
        return r

    # --------- deployments / bots ---------
    def _columns(table: str) -> set:
        with connect(db_path) as conn:
            return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _col(cols: set, alias: str, name: str, default: str = "NULL") -> str:
        if name in cols:
            return f"{alias}.{name} AS {name}"
        return f"{default} AS {name}"

    @app.get("/api/deployments")
    def api_deployments(status: Optional[str] = None, venue: Optional[str] = None,
                        strategy: Optional[str] = None, symbol: Optional[str] = None):
        cache_key = f"api:deployments:{status}:{venue}:{strategy}:{symbol}"
        cache = get_cache()
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        with connect(db_path) as conn:
            dcols = _columns("deployments")
            select_cols = [
                _col(dcols, "d", "id", "0"), _col(dcols, "d", "name", "''"),
                _col(dcols, "d", "venue", "''"), _col(dcols, "d", "strategy", "''"),
                _col(dcols, "d", "symbol", "''"), _col(dcols, "d", "resolution", "''"),
                _col(dcols, "d", "size", "1"), _col(dcols, "d", "params_json", "'{}'"),
                _col(dcols, "d", "sl_pct", "0"), _col(dcols, "d", "tp_pct", "0"),
                _col(dcols, "d", "trail_pct", "0"), _col(dcols, "d", "trail_activate_pct", "0"),
                _col(dcols, "d", "breakeven_after_pct", "0"), _col(dcols, "d", "reduce_only", "0"),
                _col(dcols, "d", "interval_sec", "300"), _col(dcols, "d", "status", "'running'"),
                _col(dcols, "d", "i_understand_live", "0"), _col(dcols, "d", "open_side"),
                _col(dcols, "d", "open_qty"), _col(dcols, "d", "open_price"),
                _col(dcols, "d", "realized_pnl", "0"), _col(dcols, "d", "ticks", "0"),
                _col(dcols, "d", "last_signal"), _col(dcols, "d", "last_tick_at"),
                _col(dcols, "d", "last_error"), _col(dcols, "d", "created_at", "''"),
                _col(dcols, "d", "started_at"), _col(dcols, "d", "stopped_at"),
                _col(dcols, "d", "peak_price"), _col(dcols, "d", "trough_price"),
                _col(dcols, "d", "trail_armed", "0"), _col(dcols, "d", "be_armed", "0"),
                _col(dcols, "d", "last_sl_px"), _col(dcols, "d", "contract_value", "1"),
                _col(dcols, "d", "leverage", "1"), _col(dcols, "d", "sync_leverage", "1"),
                _col(dcols, "d", "tag"),
            ]
            q = f"SELECT {', '.join(select_cols)} FROM deployments d"
            conds = []
            args = []
            if status:
                conds.append("d.status = ?"); args.append(status)
            if venue:
                conds.append("d.venue = ?"); args.append(venue)
            if strategy:
                conds.append("d.strategy = ?"); args.append(strategy)
            if symbol:
                conds.append("d.symbol = ?"); args.append(symbol)
            if conds:
                q += " WHERE " + " AND ".join(conds)
            q += " ORDER BY id DESC"
            cur = conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            result = [dict(zip(cols, row)) for row in cur.fetchall()]
            
            import datetime
            today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
            for r in result:
                dep_id_str = f"d_{r['id']}"
                cur_day = conn.execute("SELECT SUM(pnl) FROM trades WHERE run_id=? AND exit_ts LIKE ?", (dep_id_str, f"{today}%")).fetchone()
                r['day_pnl'] = cur_day[0] if cur_day and cur_day[0] else 0.0
                # Using 10000 as a proxy for capital if we only have lot size, or assuming size is capital
                # If size is purely qty, this is a proxy percentage. We'll use lot size directly as a base.
                r['return_pct'] = (r['realized_pnl'] / r['size']) * 100 if r.get('size') else 0.0
                
            cache.set(cache_key, result, ttl=2)
            return result

    @app.get("/api/deployment-events")
    def api_deployment_events_all(limit: int = 300, kind: Optional[str] = None,
                                  venue: Optional[str] = None, strategy: Optional[str] = None,
                                  symbol: Optional[str] = None, deployment_id: Optional[int] = None,
                                  include_ticks: int = 0):
        limit = max(1, min(int(limit or 300), 5000))
        with connect(db_path) as conn:
            ecols = _columns("deployment_events")
            dcols = _columns("deployments")
            select_cols = [
                _col(ecols, "e", "id", "0"), _col(ecols, "e", "ts", "''"),
                _col(ecols, "e", "kind", "''"), _col(ecols, "e", "message"),
                _col(ecols, "e", "order_id"), _col(ecols, "e", "pnl"),
                _col(ecols, "e", "side"), _col(ecols, "e", "qty"),
                _col(ecols, "e", "price"), _col(ecols, "e", "sl"),
                _col(ecols, "e", "tp"), _col(ecols, "e", "trail"),
                _col(ecols, "e", "upnl"), _col(ecols, "e", "equity_after"),
                _col(ecols, "e", "peak"), _col(ecols, "e", "trough"),
                _col(ecols, "e", "profit_pct"), _col(ecols, "e", "sl_px"),
                _col(ecols, "e", "snapshot_json"), _col(ecols, "e", "deployment_id", "0"),
                _col(dcols, "d", "name", "''").replace(" AS name", " AS deployment_name"),
                _col(dcols, "d", "strategy", "''"), _col(dcols, "d", "symbol", "''"),
                _col(dcols, "d", "venue", "''"),
            ]
            q = f"SELECT {', '.join(select_cols)} FROM deployment_events e JOIN deployments d ON d.id = e.deployment_id"
            conds = []
            args = []
            if kind:
                conds.append("e.kind = ?"); args.append(kind)
            elif not include_ticks:
                conds.append("e.kind <> 'tick'")
            if venue:
                conds.append("d.venue = ?"); args.append(venue)
            if strategy:
                conds.append("d.strategy = ?"); args.append(strategy)
            if symbol:
                conds.append("d.symbol = ?"); args.append(symbol)
            if deployment_id:
                conds.append("e.deployment_id = ?"); args.append(deployment_id)
            if conds:
                q += " WHERE " + " AND ".join(conds)
            q += " ORDER BY e.id DESC LIMIT ?"; args.append(limit)
            cur = conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return {"rows": [dict(zip(cols, row)) for row in cur.fetchall()]}

    @app.get("/api/deployments/{dep_id}")
    def api_deployment(dep_id: int):
        with connect(db_path) as conn:
            cur = conn.execute("SELECT * FROM deployments WHERE id=?", (dep_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "deployment not found")
            cols = [c[0] for c in cur.description]
            return dict(zip(cols, row))

    @app.get("/api/deployments/{dep_id}/events")
    def api_deployment_events(dep_id: int, limit: int = 200,
                              kind: Optional[str] = None):
        with connect(db_path) as conn:
            ecols = _columns("deployment_events")
            select_cols = [
                _col(ecols, "e", "id", "0"), _col(ecols, "e", "ts", "''"),
                _col(ecols, "e", "kind", "''"), _col(ecols, "e", "message"),
                _col(ecols, "e", "order_id"), _col(ecols, "e", "pnl"),
                _col(ecols, "e", "side"), _col(ecols, "e", "qty"),
                _col(ecols, "e", "price"), _col(ecols, "e", "sl"),
                _col(ecols, "e", "tp"), _col(ecols, "e", "trail"),
                _col(ecols, "e", "equity_after"), _col(ecols, "e", "upnl"),
                _col(ecols, "e", "peak"), _col(ecols, "e", "trough"),
                _col(ecols, "e", "profit_pct"), _col(ecols, "e", "sl_px"),
                _col(ecols, "e", "snapshot_json"), _col(ecols, "e", "deployment_id", "0"),
            ]
            q = f"SELECT {', '.join(select_cols)} FROM deployment_events e WHERE deployment_id=?"
            args: list = [dep_id]
            if kind:
                q += " AND kind = ?"; args.append(kind)
            q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
            cur = conn.execute(q, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    @app.post("/api/deployments/{dep_id}/pause")
    def api_deployment_pause(dep_id: int):
        now = datetime.utcnow().isoformat() + "Z"
        with connect(db_path) as conn:
            cur = conn.execute("UPDATE deployments SET status='paused' WHERE id=? AND status='running'", (dep_id,))
            conn.execute("INSERT INTO deployment_events(deployment_id,ts,kind,message) VALUES (?,?, 'stop', 'paused from web UI')", (dep_id, now))
            conn.commit()
            return {"ok": True, "changes": cur.rowcount}

    @app.post("/api/deployments/{dep_id}/resume")
    def api_deployment_resume(dep_id: int):
        now = datetime.utcnow().isoformat() + "Z"
        with connect(db_path) as conn:
            cur = conn.execute("UPDATE deployments SET status='running', last_error=NULL, consecutive_errors=0 WHERE id=? AND status IN ('paused','stopped')", (dep_id,))
            conn.execute("INSERT INTO deployment_events(deployment_id,ts,kind,message) VALUES (?,?, 'start', 'resumed from web UI')", (dep_id, now))
            conn.commit()
            return {"ok": True, "changes": cur.rowcount}

    @app.post("/api/deployments/resume-all-paused")
    def api_deployment_resume_all_paused():
        now = datetime.utcnow().isoformat() + "Z"
        with connect(db_path) as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM deployments WHERE status='paused'").fetchall()]
            for dep_id in ids:
                conn.execute("UPDATE deployments SET status='running', last_error=NULL, consecutive_errors=0 WHERE id=?", (dep_id,))
                conn.execute("INSERT INTO deployment_events(deployment_id,ts,kind,message) VALUES (?,?, 'start', 'resumed from web UI bulk')", (dep_id, now))
            conn.commit()
            return {"ok": True, "resumed": len(ids)}

    @app.post("/api/deployments/{dep_id}/stop")
    def api_deployment_stop(dep_id: int):
        now = datetime.utcnow().isoformat() + "Z"
        with connect(db_path) as conn:
            cur = conn.execute("UPDATE deployments SET status='stopped', stopped_at=? WHERE id=?", (now, dep_id))
            conn.execute("INSERT INTO deployment_events(deployment_id,ts,kind,message) VALUES (?,?, 'stop', 'stopped from web UI')", (dep_id, now))
            conn.commit()
            return {"ok": True, "changes": cur.rowcount}

    @app.post("/api/deployments/{dep_id}/delete")
    def api_deployment_delete(dep_id: int):
        with connect(db_path) as conn:
            conn.execute("DELETE FROM deployment_events WHERE deployment_id=?", (dep_id,))
            cur = conn.execute("DELETE FROM deployments WHERE id=?", (dep_id,))
            conn.commit()
            return {"ok": True, "deleted": cur.rowcount > 0}

    # --------- db admin / introspection ---------
    @app.get("/api/db/info")
    def api_db_info():
        return db_info(db_path=db_path)

    @app.get("/api/db/schema")
    def api_db_schema():
        return schema_info(db_path=db_path)

    @app.post("/api/db/vacuum")
    def api_db_vacuum():
        try:
            return vacuum_db(db_path=db_path)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/db/clear/{table}")
    def api_db_clear(table: str, confirm: str = ""):
        if confirm != "yes":
            raise HTTPException(400, "add ?confirm=yes to clear a table")
        try:
            return clear_table(table, db_path=db_path)
        except ValueError as e:
            raise HTTPException(400, str(e))

    # --------- scheduler control (maintenance / restart) ---------
    from fastapi import Request  # noqa: F401  (also imported at module scope below)

    def _check_admin(token: Optional[str]) -> None:
        # Auth disabled: personal project. Accept all callers.
        return


    @app.get("/api/scheduler/status")
    def api_scheduler_status():
        status = scheduler_status()
        alive = False
        try:
            hb = status.get("last_heartbeat_at")
            if hb:
                dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
                age = (datetime.now(tz=dt.tzinfo) - dt).total_seconds()
                status["heartbeat_age_sec"] = age
                alive = age < 60
        except Exception:
            pass
        status["alive"] = alive
        return status

    @app.post("/api/scheduler/restart")
    def api_scheduler_restart(request: "Request", reason: str = ""):
        _check_admin(request.headers.get("x-admin-token"))
        return request_scheduler_restart(reason=reason)

    @app.get("/api/scheduler/logs")
    def api_scheduler_logs(since_id: int = 0, limit: int = 300, level: str = ""):
        rows = scheduler_logs_tail(
            since_id=since_id,
            limit=limit,
            level=level or None,
        )
        return {"rows": rows}

    # --------- background tasks ---------
    from .store.db import list_background_tasks, toggle_background_task, get_task_logs

    @app.get("/api/tasks")
    def api_tasks():
        return list_background_tasks(db_path=db_path)
        
    @app.post("/api/tasks/seed_default")
    def api_tasks_seed_default():
        from .store.db import connect
        tasks = [
            ("Emergency Monitor", "Monitors live bot positions for extreme drawdowns and issues FLAT overrides.", 900, "emergency_monitor", "{}"),
            ("Daily Report", "Generates a daily summary of bot activity.", 86400, "daily_report", "{}"),
            ("Stat Arb Scanner", "Calculates Z-Scores on correlated pairs and deploys mean reversion on divergences.", 300, "stat_arb_scanner", '{"base_lot_size": 1.0, "auto_deploy": false}'),
            ("Efficiency Evaluator", "Analyzes historical trades to measure the impact of institutional risk-management features.", 3600, "efficiency_evaluator", "{}"),
            ("Scalp Hunter", "Searches for volatile scalping opportunities and deploys short-term bots.", 60, "scalp_hunter", "{}"),
            ("Capital Allocator", "Rebalances strategy capital based on historical win-rates and profit factors.", 14400, "capital_allocator", "{}"),
            ("Equity Monitor", "Tracks open position drawdown and closed trade equity curves for all running bots.", 300, "equity_monitor", "{}"),
            ("Funding Rate Monitor", "Monitors extreme funding rates across perpetual pairs to highlight arbitrage opportunities.", 3600, "funding_rate_monitor", "{}"),
            ("Global Exposure Manager", "Enforces portfolio-wide position limits and total USD exposure ceilings.", 600, "global_exposure_manager", "{}"),
            ("Liquidity Guard", "Monitors order book depth and warns when market order slippage exceeds thresholds.", 300, "liquidity_guard", "{}"),
            ("MTF Trend Enforcer", "Validates higher timeframe EMAs to ensure sub-minute strategies trade in line with trend.", 900, "mtf_trend_enforcer", "{}"),
            ("Runner Fleet Hunter", "Scans top turnover pairs for SMC setups and deploys long-term trend runner bots.", 300, "runner_fleet_hunter", "{}"),
            ("SMC Hunter", "Scans order blocks and fair value gaps across top pairs to discover SMC entries.", 300, "smc_hunter", "{}"),
            ("Volatility Circuit Breaker", "Monitors market flash crashes and pauses long bots during extreme market dips.", 120, "volatility_circuit_breaker", "{}"),
            ("Volatility Grid Farmer", "Identifies ranging high-volatility pairs suitable for automated grid farming.", 1800, "volatility_grid_farmer", "{}"),
            ("Volume Anomaly Sniper", "Detects sudden 5x volume spikes to capture explosive momentum breakouts.", 60, "volume_anomaly_sniper", "{}"),
            ("VWAP Reversion Hunter", "Monitors price deviations from VWAP bands to deploy mean reversion trades.", 600, "vwap_reversion_hunter", "{}"),
            ("Hyperparameter Auto-Tuner", "Periodically backtests historical candle data to auto-tune optimal SL/TP/Trailing Risk parameters.", 86400, "hyperparam_auto_tuner", '{"lookback_days": 30, "auto_apply": false}'),
            ("Liquidation Cascade Hunter", "Scans forced liquidation wicks (>3.5%) to deploy fast mean-reversion scalp bounces.", 300, "liquidation_cascade_hunter", "{}"),
            ("Funding Arbitrage Farmer", "Monitors high positive perpetual funding rates (>20% APY) for delta-neutral yield farming.", 3600, "funding_arbitrage_farmer", "{}"),
            ("Correlation Matrix Analyzer", "Calculates 30-day rolling correlations across active bots to prevent over-concentrated drawdown risks.", 14400, "correlation_matrix_analyzer", "{}"),
            ("ATR Position Sizer", "Calculates 14-period ATR across active bot symbols to maintain equal $ USD risk per trade.", 3600, "atr_position_sizer", "{}"),
            ("Webhook Dispatcher", "Dispatches real-time trade alerts and emergency notifications to Telegram & Discord webhooks.", 60, "webhook_dispatcher", "{}"),
            ("Options Delta Hedger", "Monitors net options portfolio Delta and auto-hedges via perpetual futures when Delta drifts.", 300, "options_delta_hedger", "{}"),
        ]
        with connect(db_path=db_path) as conn:
            for name, desc, interval, script, params in tasks:
                conn.execute(
                    "INSERT OR IGNORE INTO background_tasks(name, description, interval_sec, status, script_name, params_json) VALUES (?, ?, ?, 'running', ?, ?)",
                    (name, desc, interval, script, params)
                )
            conn.commit()
        return {"ok": True}
        
    @app.post("/api/tasks/{task_id}/toggle")
    def api_toggle_task(task_id: int, status: str = ""):
        if not status:
            from .store.db import connect
            with connect(db_path=db_path) as conn:
                row = conn.execute("SELECT status FROM background_tasks WHERE id=?", (task_id,)).fetchone()
                if not row:
                    from fastapi import HTTPException
                    raise HTTPException(404, "Task not found")
                status = "running" if row[0] in ("paused", "stopped") else "paused"
                
        if status not in ("running", "stopped", "paused"):
            from fastapi import HTTPException
            raise HTTPException(400, "status must be running, stopped, or paused")
        ok = toggle_background_task(task_id, status, db_path=db_path)
        return {"ok": ok, "status": status}

    @app.post("/api/tasks/{task_id}/run")
    async def api_task_run(task_id: int, request: Request):
        from .store.db import connect
        with connect(db_path=db_path) as conn:
            row = conn.execute("SELECT script_name FROM background_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                from fastapi import HTTPException
                raise HTTPException(404, "Task not found")
        
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        
        from importlib import import_module
        try:
            mod = import_module(f"delta_bt.tasks.{row[0]}")
            res = mod.run(**body)
            return {"result": str(res) if res else ""}
        except Exception as e:
            from fastapi import HTTPException
            raise HTTPException(500, str(e))


    from pydantic import BaseModel
    
    @app.post("/api/backtest")
    def api_backtest(req: BacktestRequest):
        import subprocess
        import json
        try:
            cmd = [
                sys.executable, "-m", "delta_bt", "backtest",
                "--strategy", req.strategy,
                "--symbol", req.symbol,
                "--timeframe", req.timeframe,
                "--capital", str(req.capital),
                "--fee-bps", str(req.fee_bps),
                "--slippage-bps", str(req.slippage_bps),
                "--qty-pct", str(req.qty_pct),
                "--leverage", str(req.leverage),
                "--sl-pct", str(req.sl_pct),
                "--tp-pct", str(req.tp_pct),
                "--trail-pct", str(req.trail_pct),
                "--params", json.dumps(req.params)
            ]
            if req.days is not None:
                cmd.extend(["--days", str(req.days)])
            if req.start:
                cmd.extend(["--start", req.start])
            if req.end:
                cmd.extend(["--end", req.end])
            if req.live:
                cmd.append("--live")
            else:
                cmd.append("--testnet")
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
            cmd = [
                sys.executable, "-m", "delta_bt", "scan",
                "--timeframe", req.timeframe,
                "--days", str(req.days),
                "--capital", str(req.capital),
                "--fee-bps", str(req.fee_bps),
                "--slippage-bps", str(req.slippage_bps),
                "--qty-pct", str(req.qty_pct),
                "--leverage", str(req.leverage),
                "--sl-pct", str(req.sl_pct),
                "--tp-pct", str(req.tp_pct),
                "--trail-pct", str(req.trail_pct),
                "--sort", req.sort_by,
                "--min-trades", str(req.min_trades)
            ]
            if req.strategy:
                cmd.extend(["--strategy", req.strategy])
            if req.symbol:
                cmd.extend(["--symbol", req.symbol])
            if req.top > 0:
                cmd.extend(["--top", str(req.top)])
            if req.profitable_only:
                cmd.append("--profitable-only")
            if req.adx_filter:
                cmd.append("--adx-filter")
                cmd.extend(["--adx-len", str(req.adx_len)])
                cmd.extend(["--adx-trend-min", str(req.adx_trend_min)])
                cmd.extend(["--adx-range-max", str(req.adx_range_max)])
                if req.adx_exit_on_flip:
                    cmd.append("--adx-exit-on-flip")
                if req.adx_tighten_trail_on_flip:
                    cmd.append("--adx-tighten-trail-on-flip")
            if req.save:
                cmd.append("--save")
            if req.json_output:
                cmd.append("--json")
            if req.live:
                cmd.append("--live")
            else:
                cmd.append("--testnet")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))
            
    @app.get("/api/tasks/catalog")
    def api_tasks_catalog():
        from .task_registry import get_catalog
        return get_catalog()

    @app.get("/api/tasks/{task_id}/logs")
    def api_tasks_logs(task_id: int):
        import subprocess
        try:
            cmd = [sys.executable, "-m", "delta_bt", "tasks", "logs", "--id", str(task_id), "--limit", "100"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "logs": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    @app.post("/api/tasks/action_all")
    def api_tasks_action_all(action: str = Query(..., description="pause-all or resume-all")):
        import subprocess
        try:
            if action not in ("pause-all", "resume-all"):
                raise HTTPException(400, detail="Invalid action")
            cmd = [sys.executable, "-m", "delta_bt", "tasks", action]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))
            
    @app.get("/api/deployments/{dep_id}/logs")
    def api_deployments_logs(dep_id: int):
        from .store.db import connect
        with connect(db_path) as conn:
            cur = conn.execute("SELECT ts, kind, message, order_id, pnl FROM deployment_events WHERE deployment_id=? ORDER BY ts DESC LIMIT 100", (dep_id,))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    @app.post("/api/tasks/create")
    async def api_tasks_create(req: Request):
        import subprocess
        import json
        from fastapi import HTTPException
        try:
            body = await req.json()
            cmd = [
                sys.executable, "-m", "delta_bt", "tasks", "add",
                "--name", body.get("name", ""),
                "--script", body.get("script", ""),
                "--interval", str(body.get("interval", 900)),
                "--desc", body.get("desc", ""),
                "--params", json.dumps(body.get("params", {}))
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))
            
    @app.post("/api/tasks/{task_id}/edit")
    async def api_tasks_edit(task_id: int, request: Request):
        import json
        
        body = await request.json()
        if not isinstance(body, dict):
            body = {"_raw": body}
            
        with connect(db_path=db_path) as conn:
            interval = body.pop("interval", None)
            if interval is not None:
                conn.execute("UPDATE background_tasks SET params_json=?, interval_sec=? WHERE id=?", (json.dumps(body), int(interval), task_id))
            else:
                conn.execute("UPDATE background_tasks SET params_json=? WHERE id=?", (json.dumps(body), task_id))
        return {"ok": True}
            
    @app.post("/api/tasks/{task_id}/delete")
    def api_tasks_delete(task_id: int):
        with connect(db_path=db_path) as conn:
            cur = conn.execute("DELETE FROM background_tasks WHERE id=?", (task_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Task not found")
        return {"ok": True}
            
    @app.post("/api/deployments/create")
    def api_deployments_create(req: DeployRequest):
        import subprocess
        import json
        try:
            cmd = [
                sys.executable, "-m", "delta_bt", "deployments", "add",
                "--name", req.name,
                "--venue", req.venue,
                "--strategy", req.strategy,
                "--symbol", req.symbol,
                "--timeframe", req.timeframe,
                "--lot", str(req.lot if req.lot is not None else 1.0),
                "--sl-pct", str(req.sl_pct if req.sl_pct is not None else 0.0),
                "--tp-pct", str(req.tp_pct if req.tp_pct is not None else 0.0),
                "--trail-pct", str(req.trail_pct if req.trail_pct is not None else 0.0),
                "--params", json.dumps(req.params),
                "--i-understand"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise HTTPException(500, detail=res.stderr)
            return {"ok": True, "output": res.stdout}
        except Exception as e:
            raise HTTPException(500, detail=str(e))

    return app



def _render_heatmap(run_id: str, db_path: Optional[str] = None) -> bytes:
    """Monthly PnL heatmap (year × month) from trades table."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as e:
        raise SystemExit("matplotlib not installed") from e

    trades = _load_trades(run_id, db_path)
    buckets: dict = {}
    for _side, _ent, exi, pnl in trades:
        buckets.setdefault(exi.year, [0.0] * 12)[exi.month - 1] += pnl
    years = sorted(buckets)
    if not years:
        # empty placeholder
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "no trades for this run",
                ha="center", va="center"); ax.axis("off")
    else:
        grid = np.array([buckets[y] for y in years], dtype=float)
        vmax = max(abs(grid.min()), abs(grid.max())) or 1.0
        fig, ax = plt.subplots(figsize=(11, 0.6 * len(years) + 1.6))
        im = ax.imshow(grid, cmap="RdYlGn", vmin=-vmax, vmax=vmax,
                       aspect="auto")
        ax.set_xticks(range(12))
        ax.set_xticklabels(["Jan","Feb","Mar","Apr","May","Jun",
                            "Jul","Aug","Sep","Oct","Nov","Dec"])
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels([str(y) for y in years])
        for i, y in enumerate(years):
            for j, v in enumerate(buckets[y]):
                if v:
                    ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                            fontsize=8, color="black")
        ax.set_title(f"Monthly PnL — {run_id}")
        fig.colorbar(im, ax=ax, shrink=0.7, label="PnL")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()


def serve(host: str = "127.0.0.1", port: int = 8000,
          db_path: Optional[str] = None) -> int:
    try:
        import uvicorn
    except ImportError as e:
        raise SystemExit("uvicorn not installed. Run: pip install uvicorn") from e
    app = create_app(db_path=db_path)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0

"""SQLite persistence for backtest / paper runs.

One file, no ORM. Stores runs, trades, equity points, fills, and the
full summary JSON so you can compare strategies across runs.

Default DB path: python/data/delta_bt.sqlite (override with DELTA_BT_DB env
var or pass `db_path` to save_run).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..execution.portfolio import Portfolio


DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "delta_bt.sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT UNIQUE NOT NULL,
    mode          TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    resolution    TEXT NOT NULL,
    period_start  TEXT,
    period_end    TEXT,
    params_json   TEXT,
    sl_pct        REAL, tp_pct REAL, trail_pct REAL, leverage REAL,
    starting_cap  REAL,
    ending_equity REAL,
    net_pnl       REAL,
    return_pct    REAL,
    trades        INTEGER,
    win_rate_pct  REAL,
    profit_factor REAL,
    max_dd_pct    REAL,
    sharpe        REAL,
    expectancy    REAL,
    summary_json  TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_strategy ON runs(strategy);
CREATE INDEX IF NOT EXISTS ix_runs_symbol   ON runs(symbol);
CREATE INDEX IF NOT EXISTS ix_runs_created  ON runs(created_at);

CREATE TABLE IF NOT EXISTS trades (
    run_id       TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    symbol       TEXT, side TEXT, qty REAL,
    entry_ts     TEXT, entry_price REAL,
    exit_ts      TEXT, exit_price  REAL,
    pnl          REAL, fees REAL, return_pct REAL,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS equity (
    run_id       TEXT NOT NULL,
    ts           TEXT NOT NULL,
    equity       REAL, cash REAL, position_value REAL,
    PRIMARY KEY (run_id, ts),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fills (
    run_id       TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    ts           TEXT, symbol TEXT, side TEXT,
    qty REAL, price REAL, fee REAL, tag TEXT,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS background_tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL,
    description   TEXT,
    interval_sec  INTEGER NOT NULL DEFAULT 900,
    status        TEXT NOT NULL DEFAULT 'running',
    last_run_at   TEXT,
    script_name   TEXT NOT NULL,
    params_json   TEXT,
    last_report   TEXT
);

CREATE TABLE IF NOT EXISTS task_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       INTEGER NOT NULL,
    ts            TEXT NOT NULL,
    level         TEXT NOT NULL DEFAULT 'INFO',
    message       TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES background_tasks(id) ON DELETE CASCADE
);
"""

# Additive migrations. Each column-add is wrapped in try/except so re-running
# an already-migrated DB is a no-op.
_MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN exit_reasons_json TEXT",
    "ALTER TABLE runs ADD COLUMN notes TEXT",
    "ALTER TABLE runs ADD COLUMN fee_bps REAL",
    "ALTER TABLE runs ADD COLUMN slippage_bps REAL",
    "ALTER TABLE runs ADD COLUMN qty_pct REAL",
    "ALTER TABLE runs ADD COLUMN best_trade_pnl REAL",
    "ALTER TABLE runs ADD COLUMN worst_trade_pnl REAL",
    "ALTER TABLE runs ADD COLUMN avg_hold_seconds REAL",
    "ALTER TABLE runs ADD COLUMN max_win_streak INTEGER",
    "ALTER TABLE runs ADD COLUMN max_loss_streak INTEGER",
    "ALTER TABLE runs ADD COLUMN total_fees REAL",
    "ALTER TABLE runs ADD COLUMN bars INTEGER",
    # Manual signal override: one-shot BUY/SELL/FLAT that fires on next tick then clears
    "ALTER TABLE deployments ADD COLUMN signal_override TEXT DEFAULT NULL",
    """CREATE TABLE IF NOT EXISTS background_tasks (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT UNIQUE NOT NULL,
        description   TEXT,
        interval_sec  INTEGER NOT NULL DEFAULT 900,
        status        TEXT NOT NULL DEFAULT 'running',
        last_run_at   TEXT,
        script_name   TEXT NOT NULL,
        params_json   TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS task_logs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id       INTEGER NOT NULL,
        ts            TEXT NOT NULL,
        level         TEXT NOT NULL DEFAULT 'INFO',
        message       TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES background_tasks(id) ON DELETE CASCADE
    )""",
    "ALTER TABLE background_tasks ADD COLUMN last_report TEXT",
    "ALTER TABLE background_tasks ADD COLUMN params_json TEXT",
]

TABLES = ("runs", "trades", "equity", "fills", "background_tasks", "task_logs")

_logged_path: Optional[str] = None


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _resolve_db(db_path: Optional[str] = None) -> Path:
    p = db_path or os.getenv("DELTA_BT_DB") or str(DEFAULT_DB)
    path = Path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _run_migrations(conn: sqlite3.Connection) -> None:
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            # column already exists
            pass


@contextmanager
def connect(db_path: Optional[str] = None):
    global _logged_path
    path = _resolve_db(db_path)
    _logged_path = str(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets Python + Node read/write concurrently without lock storms.
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        pass
    try:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_run(
    run_id: str,
    pf: Portfolio,
    summary: Dict,
    meta: Dict,
    db_path: Optional[str] = None,
) -> str:
    """Persist a full run. Returns the DB path used."""
    path = _resolve_db(db_path)
    with connect(str(path)) as conn:
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.execute(
            """INSERT INTO runs(
                run_id, mode, strategy, symbol, resolution,
                period_start, period_end, params_json,
                sl_pct, tp_pct, trail_pct, leverage,
                starting_cap, ending_equity, net_pnl, return_pct,
                trades, win_rate_pct, profit_factor, max_dd_pct,
                sharpe, expectancy, summary_json, created_at,
                exit_reasons_json, notes, fee_bps, slippage_bps, qty_pct,
                best_trade_pnl, worst_trade_pnl, avg_hold_seconds,
                max_win_streak, max_loss_streak, total_fees, bars
            ) VALUES (?,?,?,?,?, ?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,
                      ?,?,?,?,?, ?,?,?, ?,?,?,?)""",
            (
                run_id, meta.get("mode"), meta.get("strategy"),
                meta.get("symbol"), meta.get("resolution"),
                _iso(meta.get("start")), _iso(meta.get("end")),
                json.dumps(meta.get("params") or {}),
                meta.get("sl_pct"), meta.get("tp_pct"),
                meta.get("trail_pct"), meta.get("leverage"),
                summary.get("starting_capital"), summary.get("ending_equity"),
                summary.get("net_pnl"), summary.get("return_pct"),
                summary.get("trades"), summary.get("win_rate_pct"),
                summary.get("profit_factor"), summary.get("max_drawdown_pct"),
                summary.get("sharpe"), summary.get("expectancy"),
                json.dumps(summary, default=str),
                datetime.utcnow().isoformat(),
                json.dumps(summary.get("exit_reasons") or {}),
                meta.get("notes"),
                meta.get("fee_bps"), meta.get("slippage_bps"), meta.get("qty_pct"),
                summary.get("best_trade_pnl"), summary.get("worst_trade_pnl"),
                summary.get("avg_hold_seconds"),
                summary.get("max_win_streak"), summary.get("max_loss_streak"),
                summary.get("total_fees"), summary.get("bars"),
            ),
        )
        conn.executemany(
            """INSERT INTO trades(run_id,seq,symbol,side,qty,entry_ts,entry_price,
                exit_ts,exit_price,pnl,fees,return_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(run_id, i, t.symbol, t.side.value, t.qty,
              _iso(t.entry_ts), t.entry_price,
              _iso(t.exit_ts), t.exit_price,
              t.pnl, t.fees, t.return_pct)
             for i, t in enumerate(pf.trades)],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO equity(run_id,ts,equity,cash,position_value) VALUES (?,?,?,?,?)",
            [(run_id, _iso(e.ts), e.equity, e.cash, e.position_value)
             for e in pf.equity_curve],
        )
        conn.executemany(
            """INSERT INTO fills(run_id,seq,ts,symbol,side,qty,price,fee,tag)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(run_id, i, _iso(f.ts), f.symbol, f.side.value,
              f.qty, f.price, f.fee, f.tag)
             for i, f in enumerate(pf.fills)],
        )
    return str(path)


# ---------------------------------------------------------------- queries ---

def list_runs(limit: int = 50, strategy: Optional[str] = None,
              symbol: Optional[str] = None, db_path: Optional[str] = None) -> List[dict]:
    q = ("SELECT run_id, created_at, mode, strategy, symbol, resolution, "
         "trades, win_rate_pct, net_pnl, return_pct, max_dd_pct, sharpe, "
         "profit_factor, expectancy, sl_pct, tp_pct, trail_pct, leverage, "
         "starting_cap, ending_equity, exit_reasons_json, params_json FROM runs")
    conds, args = [], []
    if strategy: conds.append("strategy = ?"); args.append(strategy)
    if symbol:   conds.append("symbol = ?");   args.append(symbol)
    if conds:    q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with connect(db_path) as conn:
        cur = conn.execute(q, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def compare_strategies(symbol: Optional[str] = None,
                       db_path: Optional[str] = None) -> List[dict]:
    """Aggregate metrics per strategy across all stored runs."""
    q = """SELECT strategy,
                  COUNT(*)                     AS runs,
                  AVG(net_pnl)                 AS avg_net_pnl,
                  AVG(return_pct)              AS avg_return_pct,
                  AVG(win_rate_pct)            AS avg_win_rate,
                  AVG(profit_factor)           AS avg_pf,
                  AVG(max_dd_pct)              AS avg_max_dd,
                  AVG(sharpe)                  AS avg_sharpe,
                  SUM(trades)                  AS total_trades
             FROM runs"""
    args: list = []
    if symbol:
        q += " WHERE symbol = ?"; args.append(symbol)
    q += " GROUP BY strategy ORDER BY avg_return_pct DESC"
    with connect(db_path) as conn:
        cur = conn.execute(q, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_run(run_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    with connect(db_path) as conn:
        cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        run = dict(zip(cols, row))
        tcur = conn.execute(
            "SELECT * FROM trades WHERE run_id=? ORDER BY seq", (run_id,)
        )
        tcols = [c[0] for c in tcur.description]
        run["trades"] = [dict(zip(tcols, r)) for r in tcur.fetchall()]
        run["equity"] = conn.execute(
            "SELECT ts, equity FROM equity WHERE run_id=? ORDER BY ts", (run_id,)
        ).fetchall()
        return run


def get_fills(run_id: str, db_path: Optional[str] = None) -> List[dict]:
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT seq, ts, symbol, side, qty, price, fee, tag "
            "FROM fills WHERE run_id=? ORDER BY seq", (run_id,)
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------- admin ---

def db_info(db_path: Optional[str] = None) -> Dict:
    """Row counts + resolved path + file size. Safe to call anytime."""
    path = _resolve_db(db_path)
    size = path.stat().st_size if path.exists() else 0
    counts: Dict[str, int] = {}
    tables_present: List[str] = []
    with connect(str(path)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        tables_present = [r[0] for r in rows]
        for t in tables_present:
            try:
                (n,) = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
                counts[t] = int(n)
            except sqlite3.Error:
                counts[t] = -1
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    return {
        "path": str(path),
        "size_bytes": size,
        "size_mb": round(size / (1024 * 1024), 3),
        "journal_mode": journal,
        "tables": tables_present,
        "counts": counts,
    }


def vacuum_db(db_path: Optional[str] = None) -> Dict:
    """VACUUM + ANALYZE. Returns before/after size."""
    path = _resolve_db(db_path)
    before = path.stat().st_size if path.exists() else 0
    # VACUUM cannot run inside a transaction — use a dedicated connection.
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("VACUUM")
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()
    after = path.stat().st_size if path.exists() else 0
    return {"path": str(path), "before_bytes": before, "after_bytes": after,
            "reclaimed_bytes": before - after}


def clear_table(name: str, db_path: Optional[str] = None) -> Dict:
    """Delete all rows from a table (or 'all')."""
    with connect(db_path) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if name == "all":
            deleted: Dict[str, int] = {}
            for t in tables:
                if t != "sqlite_sequence":
                    try:
                        n = conn.execute(f"DELETE FROM {t}").rowcount
                        deleted[t] = int(n or 0)
                    except sqlite3.Error:
                        deleted[t] = -1
            return {"table": "all", "deleted": deleted}
        if name not in tables or name == "sqlite_sequence":
            raise ValueError(f"table not clearable or invalid: {name}")
        n = conn.execute(f"DELETE FROM {name}").rowcount
        return {"table": name, "deleted": int(n or 0)}


def schema_info(db_path: Optional[str] = None) -> Dict:
    """Return every table's columns — useful for auto-generating UIs."""
    out: Dict[str, List[Dict]] = {}
    with connect(db_path) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        for t in tables:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
            out[t] = [
                {"name": c[1], "type": c[2], "notnull": bool(c[3]),
                 "default": c[4], "pk": bool(c[5])}
                for c in cols
            ]
    return {"tables": out}


# ---------------------------------------------------------------- background tasks ---

DEFAULT_TASKS = [
    ("Emergency Monitor", "Monitored active positions safely. No emergencies detected.", 900, "running", "emergency_monitor"),
    ("Daily Report", "Daily report generator & notification dispatcher.", 86400, "running", "daily_report"),
    ("Stat Arb Scanner", "Statistical Arbitrage pair scanner.", 300, "running", "stat_arb_scanner"),
    ("Efficiency Evaluator", "Evaluates bot execution efficiency & slippage.", 3600, "running", "efficiency_evaluator"),
    ("Scalp Hunter", "Scans for 1m high-frequency scalp setups.", 60, "running", "scalp_hunter"),
    ("Capital Allocator", "Dynamically allocates capital based on Sharpe ratio.", 14400, "running", "capital_allocator"),
    ("Equity Monitor", "Tracks equity curve & flags portfolio drawdowns.", 300, "running", "equity_monitor"),
    ("Funding Rate Monitor", "Monitored perpetual funding rates across assets.", 3600, "running", "funding_rate_monitor"),
    ("Global Exposure Manager", "Enforces maximum portfolio leverage and exposure limits.", 600, "running", "global_exposure_manager"),
    ("Liquidity Guard", "Monitors orderbook depth & prevents high slippage trades.", 300, "running", "liquidity_guard"),
    ("MTF Trend Enforcer", "Enforces multi-timeframe trend alignment.", 900, "running", "mtf_trend_enforcer"),
    ("Runner Fleet Hunter", "Identifies strong trending coins and deploys runner bots.", 300, "running", "runner_fleet_hunter"),
    ("SMC Hunter", "Scans for Smart Money Concepts (OB + FVG) entries.", 300, "running", "smc_hunter"),
    ("Auto-Scan One-Cycle", "Scans market, ranks setups, deploys a single one-cycle trade per signal. Bot auto-stops after first TP/SL.", 300, "paused", "auto_scan_one_cycle"),
    ("Volatility Circuit Breaker", "Halts trading during sudden market volatility spikes.", 120, "running", "volatility_circuit_breaker"),
    ("Volatility Grid Farmer", "Deploys dynamic grid bots on high volatility assets.", 1800, "running", "volatility_grid_farmer"),
    ("Volume Anomaly Sniper", "Snipes high volume breakout anomalies.", 60, "running", "volume_anomaly_sniper"),
    ("VWAP Reversion Hunter", "Scans for extreme price deviations from daily VWAP.", 600, "running", "vwap_reversion_hunter"),
    ("Hyperparameter Auto-Tuner", "Runs automated strategy hyperparameter optimization.", 86400, "running", "hyperparam_auto_tuner"),
    ("Liquidation Cascade Hunter", "Snipes liquidation cascade reversals.", 300, "running", "liquidation_cascade_hunter"),
    ("Funding Arbitrage Farmer", "Farms funding rate yield arbitrage opportunities.", 3600, "running", "funding_arbitrage_farmer"),
    ("Correlation Matrix Analyzer", "Monitors cross-asset price correlations.", 14400, "running", "correlation_matrix_analyzer"),
    ("ATR Position Sizer", "Dynamically sizes positions using ATR volatility.", 3600, "running", "atr_position_sizer"),
    ("Webhook Dispatcher", "Dispatches real-time webhooks & Telegram alerts.", 60, "running", "webhook_dispatcher"),
    ("Options Delta Hedger", "Dynamically delta-hedges open options positions.", 300, "running", "options_delta_hedger"),
]

def list_background_tasks(db_path: Optional[str] = None) -> List[dict]:
    with connect(db_path) as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM background_tasks").fetchone()[0]
        if cnt == 0:
            for name, desc, interval, status, script in DEFAULT_TASKS:
                conn.execute(
                    "INSERT INTO background_tasks(name, description, interval_sec, status, script_name, params_json) "
                    "VALUES (?, ?, ?, ?, ?, '{}')",
                    (name, desc, interval, status, script)
                )
        cur = conn.execute("SELECT * FROM background_tasks ORDER BY id ASC")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

def toggle_background_task(task_id: int, status: str, db_path: Optional[str] = None) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute("UPDATE background_tasks SET status=? WHERE id=?", (status, task_id))
        return cur.rowcount > 0

def get_task_logs(task_id: int, limit: int = 100, db_path: Optional[str] = None) -> List[dict]:
    with connect(db_path) as conn:
        cur = conn.execute("SELECT * FROM task_logs WHERE task_id=? ORDER BY ts DESC LIMIT ?", (task_id, limit))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

def log_task(task_id: int, level: str, message: str, db_path: Optional[str] = None):
    try:
        with connect(db_path) as conn:
            conn.execute("INSERT INTO task_logs(task_id, ts, level, message) VALUES (?, ?, ?, ?)",
                         (task_id, datetime.utcnow().isoformat() + "Z", level, message))
    except Exception:
        # Silently ignore — task may have been deleted while running
        pass

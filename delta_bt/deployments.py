"""Deployment registry — shared with the web UI via the same SQLite DB.

Rows describe a scheduled strategy: which venue, symbol, resolution, size,
params, risk knobs, and cadence. The `watch` scheduler in scheduler.py
picks up running rows and evaluates them on each interval.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "delta_bt.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS deployments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  venue TEXT NOT NULL,
  strategy TEXT NOT NULL,
  symbol TEXT NOT NULL,
  resolution TEXT NOT NULL,
  size REAL NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  sl_pct REAL NOT NULL DEFAULT 0,
  tp_pct REAL NOT NULL DEFAULT 0,
  trail_pct REAL NOT NULL DEFAULT 0,
  reduce_only INTEGER NOT NULL DEFAULT 0,
  interval_sec INTEGER NOT NULL DEFAULT 300,
  status TEXT NOT NULL DEFAULT 'running',
  i_understand_live INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  stopped_at TEXT,
  last_tick_at TEXT,
  last_signal TEXT,
  last_error TEXT,
  realized_pnl REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_deployments_status ON deployments(status);
CREATE TABLE IF NOT EXISTS deployment_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deployment_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  message TEXT,
  order_id TEXT,
  pnl REAL,
  FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_events_dep ON deployment_events(deployment_id, id DESC);
CREATE TABLE IF NOT EXISTS scheduler_control (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  restart_requested INTEGER NOT NULL DEFAULT 0,
  restart_reason TEXT,
  restart_requested_at TEXT,
  last_heartbeat_at TEXT,
  last_restart_at TEXT,
  pid INTEGER,
  version TEXT
);
INSERT OR IGNORE INTO scheduler_control(id) VALUES(1);
CREATE TABLE IF NOT EXISTS scheduler_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'INFO',
  msg TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_scheduler_logs_id ON scheduler_logs(id DESC);
"""

# Additive columns for richer bot event logs + paper-position tracking.
_EVENT_MIGRATIONS = [
    "ALTER TABLE deployment_events ADD COLUMN side TEXT",
    "ALTER TABLE deployment_events ADD COLUMN qty REAL",
    "ALTER TABLE deployment_events ADD COLUMN price REAL",
    "ALTER TABLE deployment_events ADD COLUMN sl REAL",
    "ALTER TABLE deployment_events ADD COLUMN tp REAL",
    "ALTER TABLE deployment_events ADD COLUMN trail REAL",
    "ALTER TABLE deployment_events ADD COLUMN equity_after REAL",
    "ALTER TABLE deployment_events ADD COLUMN upnl REAL",
    "ALTER TABLE deployments ADD COLUMN prior_signal TEXT",
    "ALTER TABLE deployments ADD COLUMN open_side TEXT",
    "ALTER TABLE deployments ADD COLUMN open_qty REAL",
    "ALTER TABLE deployments ADD COLUMN open_price REAL",
    "ALTER TABLE deployments ADD COLUMN ticks INTEGER DEFAULT 0",
    # Dynamic / profit-activated trailing stop + breakeven lock:
    "ALTER TABLE deployments ADD COLUMN trail_activate_pct REAL NOT NULL DEFAULT 0",
    "ALTER TABLE deployments ADD COLUMN breakeven_after_pct REAL NOT NULL DEFAULT 0",
    "ALTER TABLE deployments ADD COLUMN peak_price REAL",
    "ALTER TABLE deployments ADD COLUMN trough_price REAL",
    "ALTER TABLE deployments ADD COLUMN trail_armed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE deployments ADD COLUMN be_armed INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE deployments ADD COLUMN consecutive_errors INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE deployments ADD COLUMN last_sl_px REAL",
    "ALTER TABLE deployment_events ADD COLUMN peak REAL",
    "ALTER TABLE deployment_events ADD COLUMN trough REAL",
    "ALTER TABLE deployment_events ADD COLUMN profit_pct REAL",
    "ALTER TABLE deployment_events ADD COLUMN sl_px REAL",
    # Exchange-side bracket orders (Delta reduce-only stops).
    "ALTER TABLE deployments ADD COLUMN sl_order_id INTEGER",
    "ALTER TABLE deployments ADD COLUMN tp_order_id INTEGER",
    "ALTER TABLE deployments ADD COLUMN sl_stop_price REAL",
    "ALTER TABLE deployments ADD COLUMN tp_stop_price REAL",
    "ALTER TABLE deployments ADD COLUMN exchange_brackets INTEGER NOT NULL DEFAULT 1",
    # Position leverage (mirror of TS column) — used to convert stored UPNL %
    # risk thresholds to raw price % for SL/TP/trail math.
    "ALTER TABLE deployments ADD COLUMN leverage REAL NOT NULL DEFAULT 1",
    # v2 risk semantics: sl/tp/trail pcts are UPNL %, divided by leverage
    # internally to get price %. Legacy rows are migrated in-place below.
    "ALTER TABLE deployments ADD COLUMN risk_semantics_v2 INTEGER NOT NULL DEFAULT 0",
    # Auto-sync leverage to Delta before each entry (matches TS schema).
    "ALTER TABLE deployments ADD COLUMN sync_leverage INTEGER NOT NULL DEFAULT 1",

]


def db_path() -> Path:
    p = os.getenv("DELTA_BT_DB")
    return Path(p) if p else DEFAULT_DB


@contextmanager
def open_db() -> Iterator[sqlite3.Connection]:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        pass
    c.executescript(SCHEMA)
    for stmt in _EVENT_MIGRATIONS:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass
    # One-shot legacy risk-semantics upgrade — see schema.server.ts for details.
    try:
        c.executescript(
            """
            UPDATE deployments
               SET sl_pct = sl_pct * leverage,
                   tp_pct = tp_pct * leverage,
                   trail_pct = trail_pct * leverage,
                   trail_activate_pct = trail_activate_pct * leverage,
                   breakeven_after_pct = breakeven_after_pct * leverage,
                   risk_semantics_v2 = 1
             WHERE (risk_semantics_v2 IS NULL OR risk_semantics_v2 = 0)
               AND leverage > 1;
            UPDATE deployments SET risk_semantics_v2 = 1
             WHERE risk_semantics_v2 IS NULL OR risk_semantics_v2 = 0;
            """
        )
    except sqlite3.OperationalError:
        pass
    try:
        yield c
        c.commit()
    finally:
        c.close()


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def add_deployment(**k: Any) -> int:
    with open_db() as c:
        cur = c.execute(
            """INSERT INTO deployments(name,venue,strategy,symbol,resolution,size,params_json,
                 sl_pct,tp_pct,trail_pct,reduce_only,interval_sec,status,i_understand_live,
                 created_at,started_at)
               VALUES(?,?,?,?,?,?,?, ?,?,?, ?,?, 'running', ?, ?, ?)""",
            (
                k["name"], k["venue"], k["strategy"], k["symbol"].upper(),
                k["resolution"], float(k["size"]),
                json.dumps(k.get("params") or {}),
                float(k.get("sl_pct") or 0), float(k.get("tp_pct") or 0),
                float(k.get("trail_pct") or 0),
                1 if k.get("reduce_only") else 0,
                int(k.get("interval_sec") or 300),
                1 if k.get("i_understand_live") else 0,
                now_iso(), now_iso(),
            ),
        )
        dep_id = int(cur.lastrowid)
        c.execute(
            "INSERT INTO deployment_events(deployment_id,ts,kind,message) VALUES (?,?,?,?)",
            (dep_id, now_iso(), "start", "created by CLI"),
        )
        return dep_id


def list_deployments() -> List[sqlite3.Row]:
    with open_db() as c:
        return list(c.execute("SELECT * FROM deployments ORDER BY id DESC"))


def get_deployment(dep_id: int) -> Optional[sqlite3.Row]:
    with open_db() as c:
        return c.execute("SELECT * FROM deployments WHERE id=?", (dep_id,)).fetchone()


def set_status(dep_id: int, status: str, msg: str = "") -> None:
    with open_db() as c:
        if status == "stopped":
            c.execute("UPDATE deployments SET status=?, stopped_at=? WHERE id=?",
                      (status, now_iso(), dep_id))
        else:
            c.execute("UPDATE deployments SET status=?, last_error=NULL WHERE id=?", (status, dep_id))
        c.execute("INSERT INTO deployment_events(deployment_id,ts,kind,message) VALUES (?,?,?,?)",
                  (dep_id, now_iso(), status if status in ("stopped",) else "start", msg or status))


def remove_deployment(dep_id: int) -> None:
    row = get_deployment(dep_id)
    if not row:
        raise ValueError("Deployment not found")
    if row["status"] != "stopped":
        raise ValueError("Stop the deployment before removing it")
    with open_db() as c:
        c.execute("DELETE FROM deployments WHERE id=?", (dep_id,))


def record_event(dep_id: int, kind: str, message: str = "", order_id: str = "", pnl: Optional[float] = None) -> None:
    with open_db() as c:
        c.execute(
            "INSERT INTO deployment_events(deployment_id,ts,kind,message,order_id,pnl) VALUES (?,?,?,?,?,?)",
            (dep_id, now_iso(), kind, message, order_id or None, pnl),
        )


MAX_CONSECUTIVE_ERRORS = 5


def _is_transient_warmup_error(err: str) -> bool:
    text = (err or "").lower()
    return (
        "not enough bars" in text
        or "warm" in text
        or "insufficient" in text
    )


def update_tick(dep_id: int, signal: str, err: Optional[str] = None) -> None:
    with open_db() as c:
        if err:
            if _is_transient_warmup_error(err):
                c.execute(
                    "UPDATE deployments SET last_tick_at=?, last_signal=?, last_error=?, "
                    "ticks = COALESCE(ticks,0) + 1, consecutive_errors = 0 WHERE id=?",
                    (now_iso(), signal, err, dep_id),
                )
                return
            c.execute(
                "UPDATE deployments SET last_tick_at=?, last_signal=?, last_error=?, "
                "ticks = COALESCE(ticks,0) + 1, "
                "consecutive_errors = COALESCE(consecutive_errors,0) + 1 WHERE id=?",
                (now_iso(), signal, err, dep_id),
            )
            row = c.execute(
                "SELECT consecutive_errors, status FROM deployments WHERE id=?", (dep_id,)
            ).fetchone()
            if row and (row[0] or 0) >= MAX_CONSECUTIVE_ERRORS and row[1] == "running":
                c.execute("UPDATE deployments SET status='paused' WHERE id=?", (dep_id,))
                c.execute(
                    "INSERT INTO deployment_events(deployment_id,ts,kind,message) VALUES (?,?,?,?)",
                    (dep_id, now_iso(), "pause",
                     f"auto-paused after {row[0]} consecutive errors"),
                )
        else:
            c.execute(
                "UPDATE deployments SET last_tick_at=?, last_signal=?, last_error=NULL, "
                "ticks = COALESCE(ticks,0) + 1, consecutive_errors = 0 WHERE id=?",
                (now_iso(), signal, dep_id),
            )



def add_realized(dep_id: int, pnl: float) -> None:
    with open_db() as c:
        c.execute("UPDATE deployments SET realized_pnl = realized_pnl + ? WHERE id=?", (pnl, dep_id))


def record_event_full(
    dep_id: int,
    kind: str,
    *,
    message: str = "",
    order_id: str = "",
    pnl: Optional[float] = None,
    side: Optional[str] = None,
    qty: Optional[float] = None,
    price: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    trail: Optional[float] = None,
    equity_after: Optional[float] = None,
    upnl: Optional[float] = None,
    peak: Optional[float] = None,
    trough: Optional[float] = None,
    profit_pct: Optional[float] = None,
    sl_px: Optional[float] = None,
) -> None:
    """Rich event insert. Prefer this over record_event for entry/exit/sl_hit/tp_hit."""
    with open_db() as c:
        c.execute(
            """INSERT INTO deployment_events(
                 deployment_id, ts, kind, message, order_id, pnl,
                 side, qty, price, sl, tp, trail, equity_after, upnl,
                 peak, trough, profit_pct, sl_px
               ) VALUES (?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?)""",
            (dep_id, now_iso(), kind, message, order_id or None, pnl,
             side, qty, price, sl, tp, trail, equity_after, upnl,
             peak, trough, profit_pct, sl_px),
        )
        
    try:
        if kind in ("error", "sl_hit", "tp_hit", "flip", "close", "entry_blocked"):
            from delta_bt.notifier import send_telegram_alert
            icon = "🚨" if kind in ("error", "sl_hit", "entry_blocked") else "✅" if kind == "tp_hit" else "⚠️"
            msg = f"{icon} <b>Bot #{dep_id} [{kind}]</b>\n<pre>{message}</pre>"
            if pnl is not None:
                msg += f"\n<b>PnL:</b> {pnl:.4f}"
            send_telegram_alert(msg)
    except Exception:
        pass


def set_open_position(dep_id: int, side: Optional[str], qty: Optional[float],
                      price: Optional[float]) -> None:
    """Set (or clear) the open position, and reset peak/trough + trail-armed
    flags so the dynamic profit-activated trail restarts fresh each trade."""
    with open_db() as c:
        if side is None:
            c.execute(
                """UPDATE deployments
                     SET open_side=NULL, open_qty=NULL, open_price=NULL,
                         peak_price=NULL, trough_price=NULL,
                          trail_armed=0, be_armed=0, last_sl_px=NULL
                   WHERE id=?""",
                (dep_id,),
            )
        else:
            c.execute(
                """UPDATE deployments
                     SET open_side=?, open_qty=?, open_price=?,
                         peak_price=?, trough_price=?,
                          trail_armed=0, be_armed=0, last_sl_px=NULL
                   WHERE id=?""",
                (side, qty, price, price, price, dep_id),
            )


def _effective_sl_px(side: str, entry: float, sl_pct: float, trail_pct: float,
                     peak: float, trough: float, trail_armed: int,
                     be_armed: int) -> Optional[float]:
    if side == "buy":
        sl_px = entry * (1 - sl_pct / 100.0) if sl_pct else None
        if be_armed:
            sl_px = entry if sl_px is None else max(sl_px, entry)
        if trail_pct and trail_armed:
            trail_px = peak * (1 - trail_pct / 100.0)
            sl_px = trail_px if sl_px is None else max(sl_px, trail_px)
        return sl_px
    sl_px = entry * (1 + sl_pct / 100.0) if sl_pct else None
    if be_armed:
        sl_px = entry if sl_px is None else min(sl_px, entry)
    if trail_pct and trail_armed:
        trail_px = trough * (1 + trail_pct / 100.0)
        sl_px = trail_px if sl_px is None else min(sl_px, trail_px)
    return sl_px


def _lev(row_or_val) -> float:
    """Return the effective leverage divisor (>=1). Accepts a sqlite Row or a
    plain number for convenience."""
    try:
        v = float(row_or_val["leverage"]) if hasattr(row_or_val, "keys") else float(row_or_val)
    except (TypeError, ValueError, IndexError, KeyError):
        v = 1.0
    return v if v and v > 1.0 else 1.0


def update_peak_and_arm(dep_id: int, side: str, entry: float, mark: float,
                        trail_pct_ui: float, trail_activate_pct_ui: float,
                        breakeven_after_pct_ui: float,
                        sl_pct_ui: float = 0.0) -> dict:
    """Update peak/trough and sticky trail_armed / be_armed flags based on risk modes (% / point / atr)."""
    with open_db() as c:
        row = c.execute(
            "SELECT peak_price, trough_price, trail_armed, be_armed, last_sl_px, leverage, params_json FROM deployments WHERE id=?",
            (dep_id,),
        ).fetchone()
        lev = _lev(row) if row else 1.0

        params = {}
        try:
            raw_p = row["params_json"] if row and row["params_json"] else "{}"
            params = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
        except Exception:
            params = {}

        trail_activate_type = str(params.get("trail_activate_type", "pct")).lower()
        breakeven_after_type = str(params.get("breakeven_after_type", "pct")).lower()
        atr_val = float(params.get("atr_value") or params.get("atr") or 0.0)

        sl_pct = float(sl_pct_ui) / lev
        trail_pct = float(trail_pct_ui) / lev
        trail_activate_val = float(trail_activate_pct_ui)
        breakeven_after_val = float(breakeven_after_pct_ui)

        peak = float(row["peak_price"]) if row and row["peak_price"] is not None else entry
        trough = float(row["trough_price"]) if row and row["trough_price"] is not None else entry
        trail_armed = int(row["trail_armed"] if row else 0)
        be_armed = int(row["be_armed"] if row else 0)
        prev_sl_px = float(row["last_sl_px"]) if row and row["last_sl_px"] is not None else None
        was_trail_armed = trail_armed
        was_be_armed = be_armed

        if side == "buy":
            peak = max(peak, mark)
            profit_pct = (mark - entry) / entry * 100.0 if entry else 0.0
            best_profit_dist = max(0.0, peak - entry)
        else:
            trough = min(trough, mark)
            profit_pct = (entry - mark) / entry * 100.0 if entry else 0.0
            best_profit_dist = max(0.0, entry - trough)

        best_profit_pct = (best_profit_dist / entry * 100.0) if entry else 0.0

        # Check trail arming
        if not trail_armed and trail_activate_val > 0:
            if trail_activate_type == "point":
                if best_profit_dist >= trail_activate_val:
                    trail_armed = 1
            elif trail_activate_type == "atr" and atr_val > 0:
                if best_profit_dist >= (trail_activate_val * atr_val):
                    trail_armed = 1
            else:  # pct
                if best_profit_pct >= (trail_activate_val / lev):
                    trail_armed = 1
        elif not trail_armed and trail_pct > 0 and trail_activate_val <= 0:
            trail_armed = 1

        # Check breakeven arming
        if not be_armed and breakeven_after_val > 0:
            if breakeven_after_type == "point":
                if best_profit_dist >= breakeven_after_val:
                    be_armed = 1
            elif breakeven_after_type == "atr" and atr_val > 0:
                if best_profit_dist >= (breakeven_after_val * atr_val):
                    be_armed = 1
            else:  # pct
                if best_profit_pct >= (breakeven_after_val / lev):
                    be_armed = 1

        new_sl_px = _effective_sl_px(side, entry, sl_pct, trail_pct, peak, trough, trail_armed, be_armed)
        c.execute(
            """UPDATE deployments
                 SET peak_price=?, trough_price=?, trail_armed=?, be_armed=?, last_sl_px=?
               WHERE id=?""",
            (peak, trough, trail_armed, be_armed, new_sl_px, dep_id),
        )
        base = dict(price=mark, peak=peak, trough=trough, profit_pct=profit_pct, sl_px=new_sl_px)
        if not was_trail_armed and trail_armed:
            c.execute(
                """INSERT INTO deployment_events(deployment_id,ts,kind,message,price,peak,trough,profit_pct,sl_px)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (dep_id, now_iso(), "trail_arm",
                 f"trail armed @ {mark:.4f} (profit {profit_pct:.2f}%, trail {trail_pct}%)",
                 base["price"], base["peak"], base["trough"], base["profit_pct"], base["sl_px"]),
            )
        if not was_be_armed and be_armed:
            c.execute(
                """INSERT INTO deployment_events(deployment_id,ts,kind,message,price,peak,trough,profit_pct,sl_px)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (dep_id, now_iso(), "be_arm",
                 f"breakeven armed @ {mark:.4f} (profit {profit_pct:.2f}%)",
                 base["price"], base["peak"], base["trough"], base["profit_pct"], base["sl_px"]),
            )
        if new_sl_px is not None and prev_sl_px is not None and abs(new_sl_px - prev_sl_px) > 1e-9:
            c.execute(
                """INSERT INTO deployment_events(deployment_id,ts,kind,message,price,peak,trough,profit_pct,sl_px)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (dep_id, now_iso(), "sl_move",
                 f"sl {prev_sl_px:.4f} → {new_sl_px:.4f}",
                 base["price"], base["peak"], base["trough"], base["profit_pct"], base["sl_px"]),
            )
        return {"peak": peak, "trough": trough, "trail_armed": trail_armed, "be_armed": be_armed, "last_sl_px": new_sl_px}


def set_prior_signal(dep_id: int, signal: str) -> None:
    with open_db() as c:
        c.execute("UPDATE deployments SET prior_signal=? WHERE id=?", (signal, dep_id))



def get_events(dep_id: int, limit: int = 50) -> List[sqlite3.Row]:
    with open_db() as c:
        return list(c.execute(
            "SELECT id,ts,kind,message,order_id,pnl FROM deployment_events WHERE deployment_id=? ORDER BY id DESC LIMIT ?",
            (dep_id, limit),
        ))


# --------- scheduler control (maintenance / restart flag) ---------

def scheduler_heartbeat(pid: int, version: str = "") -> None:
    with open_db() as c:
        c.execute(
            "UPDATE scheduler_control SET last_heartbeat_at=?, pid=?, version=? WHERE id=1",
            (now_iso(), int(pid), version),
        )


def scheduler_status() -> Dict[str, Any]:
    with open_db() as c:
        row = c.execute(
            "SELECT restart_requested, restart_reason, restart_requested_at, "
            "last_heartbeat_at, last_restart_at, pid, version "
            "FROM scheduler_control WHERE id=1"
        ).fetchone()
    if not row:
        return {}
    return {k: row[k] for k in row.keys()}


def request_scheduler_restart(reason: str = "") -> Dict[str, Any]:
    with open_db() as c:
        c.execute(
            "UPDATE scheduler_control SET restart_requested=1, restart_reason=?, restart_requested_at=? WHERE id=1",
            (reason or None, now_iso()),
        )
    return {"ok": True, "requested_at": now_iso()}


def consume_scheduler_restart() -> Optional[str]:
    """Called by the scheduler loop. Returns the reason if a restart is pending
    and clears the flag; otherwise None."""
    with open_db() as c:
        row = c.execute(
            "SELECT restart_requested, restart_reason FROM scheduler_control WHERE id=1"
        ).fetchone()
        if not row or not row["restart_requested"]:
            return None
        c.execute(
            "UPDATE scheduler_control SET restart_requested=0, restart_reason=NULL, "
            "last_restart_at=? WHERE id=1",
            (now_iso(),),
        )
        return row["restart_reason"] or ""


# --------- scheduler logs (ring buffer, capped) ---------

_SCHED_LOG_CAP = 5000  # keep the most recent N rows

def scheduler_log(msg: str, level: str = "INFO") -> None:
    """Append a log line and prune older rows beyond the cap. Never raises."""
    try:
        with open_db() as c:
            c.execute(
                "INSERT INTO scheduler_logs(ts, level, msg) VALUES(?,?,?)",
                (now_iso(), (level or "INFO").upper()[:8], str(msg)[:4000]),
            )
            # Prune anything older than the newest _SCHED_LOG_CAP rows.
            c.execute(
                "DELETE FROM scheduler_logs WHERE id <= ("
                "  SELECT COALESCE(MAX(id),0) - ? FROM scheduler_logs"
                ")",
                (_SCHED_LOG_CAP,),
            )
    except Exception:
        # Logging must never take down the scheduler.
        pass


def scheduler_logs_tail(since_id: int = 0, limit: int = 300,
                        level: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(2000, int(limit)))
    since_id = max(0, int(since_id))
    q = "SELECT id, ts, level, msg FROM scheduler_logs WHERE id > ?"
    args: List[Any] = [since_id]
    if level:
        q += " AND level = ?"
        args.append(level.upper())
    q += " ORDER BY id ASC LIMIT ?"
    args.append(limit)
    with open_db() as c:
        rows = c.execute(q, args).fetchall()
    return [{"id": r["id"], "ts": r["ts"], "level": r["level"], "msg": r["msg"]} for r in rows]

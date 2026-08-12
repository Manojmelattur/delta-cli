#!/usr/bin/env python3
"""
run_task.py — Execute a single delta-cli background task by ID.

This replaces the persistent `watch --interval 15` loop with individual
cronjob invocations, reducing memory usage on resource-constrained boxes.

Usage:
  venv/bin/python -m delta_bt run-task --id 82
  venv/bin/python -m delta_bt run-task --id 82 97 99
  venv/bin/python -m delta_bt run-task --all

Each task runs independently: import module, execute run(), log result.
No persistent process = no OOM risk.
"""
import sys
import os
import json
import argparse
from importlib import import_module
from datetime import datetime, timezone

# Ensure we can import delta_bt
sys.path.insert(0, "/root/delta-cli")

from delta_bt.store.db import connect, list_background_tasks, log_task


def run_task(task_id: int) -> bool:
    """Run a single background task by ID. Returns True on success."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, script_name, params_json FROM background_tasks WHERE id=? AND status='running'",
            (task_id,),
        ).fetchone()

    if not row:
        print(f"Task {task_id}: not found or not running")
        return False

    tid, name, script_name, params_json = row["id"], row["name"], row["script_name"], row["params_json"]
    params = json.loads(params_json) if params_json else {}

    try:
        module_name = script_name.removesuffix(".py")
        mod = import_module(f"delta_bt.tasks.{module_name}")
        result = mod.run(**params)

        if result:
            log_task(tid, "INFO", str(result))
            print(f"Task {tid} {name}: OK")
            return True
        else:
            log_task(tid, "INFO", "Completed (no output)")
            print(f"Task {tid} {name}: OK (no output)")
            return True

    except Exception as e:
        log_task(tid, "ERROR", f"Task failed: {e}")
        print(f"Task {tid} {name}: ERROR — {e}")
        return False


def run_all() -> dict:
    """Run all running background tasks whose interval has elapsed."""
    results = {"success": 0, "failed": 0, "skipped": 0, "total": 0}

    with connect() as conn:
        conn.row_factory = __import__("sqlite3").Row
        tasks = conn.execute(
            "SELECT id, name, script_name, params_json, interval_sec, last_run_at, status "
            "FROM background_tasks WHERE status='running' ORDER BY id"
        ).fetchall()

    for t in tasks:
        results["total"] += 1
        last = t["last_run_at"]
        if last:
            try:
                prev = datetime.fromisoformat(last.replace("Z", "+00:00"))
                elapsed = (datetime.now(tz=timezone.utc) - prev).total_seconds()
                if elapsed < t["interval_sec"]:
                    results["skipped"] += 1
                    continue
            except ValueError:
                pass

        if run_task(t["id"]):
            results["success"] += 1
        else:
            results["failed"] += 1

    return results


def main():
    parser = argparse.ArgumentParser(description="Run a delta-cli background task")
    parser.add_argument("--id", type=int, nargs="+", help="Task ID(s) to run")
    parser.add_argument("--all", action="store_true", help="Run all eligible tasks")
    args = parser.parse_args()

    if args.all:
        r = run_all()
        print(f"\nRun all: {r['success']} succeeded, {r['failed']} failed, {r['skipped']} skipped (of {r['total']} total)")
    elif args.id:
        for tid in args.id:
            run_task(tid)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

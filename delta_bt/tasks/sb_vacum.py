"""Database Vacuum and Cleanup Task

Keeps the SQLite database lean and fast by:
  1. Deleting old deployment_events beyond retention_days
  2. Deleting old scheduler_logs beyond log_retention_days
  3. Deleting stopped/paused deployments older than deployment_retention_days
     that have no open position (safe to archive)
  4. Running VACUUM to reclaim disk space and defragment the DB
  5. Running ANALYZE to update query planner statistics

Without regular cleanup:
  - deployment_events grows unbounded (tick events every 15s per bot)
  - scheduler_logs fills up with INFO noise
  - SQLite file size bloats and queries slow down

Params (set in task params_json):
    retention_days            : Keep deployment_events for this many days (default 90)
    log_retention_days        : Keep scheduler_logs for this many days (default 30)
    deployment_retention_days : Keep stopped deployments for this many days (default 180)
    keep_kinds                : Event kinds to always keep regardless of age
                                (default entry, sl_hit, tp_hit, signal_exit)
    dry_run                   : If True, reports what would be deleted without deleting (default False)
    run_vacuum                : If True, runs VACUUM after cleanup (default True)
"""
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from typing import List

from delta_bt.store.db import connect


_DEFAULT_KEEP_KINDS = {
    "entry", "sl_hit", "tp_hit", "signal_exit",
    "sl_slippage", "flip", "exchange_sync_close",
    "atr_risk_update", "capital_allocator",
    "equity_monitor", "leverage_audit",
    "max_drawdown_guard", "circuit_breaker",
}


def _count_rows(conn, table: str, where: str = "", args: list = None) -> int:
    """Count rows in a table with optional WHERE clause."""
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql, args or []).fetchone()
    return int(row[0] or 0)


def _db_size_mb() -> float:
    """Return current SQLite DB file size in MB."""
    try:
        db_path = os.getenv("DELTA_BT_DB")
        if not db_path:
            from pathlib import Path
            db_path = str(
                Path(__file__).resolve().parents[2] / "data" / "delta_bt.sqlite"
            )
        return os.path.getsize(db_path) / (1024 * 1024)
    except Exception:
        return 0.0


def run(**kwargs):
    retention_days            = int(kwargs.get("retention_days",            90))
    log_retention_days        = int(kwargs.get("log_retention_days",        30))
    deployment_retention_days = int(kwargs.get("deployment_retention_days", 180))
    dry_run                   = bool(kwargs.get("dry_run",                  False))
    run_vacuum                = bool(kwargs.get("run_vacuum",               True))
    custom_keep_kinds         = kwargs.get("keep_kinds",                    None)

    keep_kinds = (
        set(custom_keep_kinds)
        if custom_keep_kinds
        else _DEFAULT_KEEP_KINDS
    )

    now     = datetime.now(timezone.utc)
    now_str = now.isoformat() + "Z"

    event_cutoff      = (now - timedelta(days=retention_days)).isoformat()      + "Z"
    log_cutoff        = (now - timedelta(days=log_retention_days)).isoformat()  + "Z"
    deploy_cutoff     = (now - timedelta(days=deployment_retention_days)).isoformat() + "Z"

    messages = [
        f"Database Vacuum and Cleanup",
        f"  Dry run              : {dry_run}",
        f"  Event retention      : {retention_days} days (cutoff={event_cutoff[:10]})",
        f"  Log retention        : {log_retention_days} days (cutoff={log_cutoff[:10]})",
        f"  Deployment retention : {deployment_retention_days} days",
        f"  Keep event kinds     : {', '.join(sorted(keep_kinds))}",
        "",
    ]

    size_before = _db_size_mb()
    messages.append(f"DB size before: {size_before:.2f} MB")

    deleted_events      = 0
    deleted_logs        = 0
    deleted_deployments = 0
    errors              = []

    with connect() as conn:
        conn.row_factory = sqlite3.Row

        # ------------------------------------------------------------------
        # Step 1 — Count and delete old deployment_events
        # Preserve important kinds (entry, sl_hit, tp_hit etc.) regardless of age
        # ------------------------------------------------------------------
        kind_placeholders = ",".join(["?"] * len(keep_kinds))

        count_deletable_events = _count_rows(
            conn,
            "deployment_events",
            f"ts < ? AND kind NOT IN ({kind_placeholders})",
            [event_cutoff, *keep_kinds],
        )

        messages.append(
            f"deployment_events older than {retention_days}d "
            f"(excluding kept kinds): {count_deletable_events} rows"
        )

        if not dry_run and count_deletable_events > 0:
            try:
                conn.execute(
                    f"DELETE FROM deployment_events "
                    f"WHERE ts < ? AND kind NOT IN ({kind_placeholders})",
                    [event_cutoff, *keep_kinds],
                )
                deleted_events = count_deletable_events
                messages.append(
                    f"  Deleted {deleted_events} old deployment_events."
                )
            except Exception as e:
                errors.append(f"ERR | deployment_events delete failed — {e}")

        # ------------------------------------------------------------------
        # Step 2 — Count and delete old scheduler_logs
        # ------------------------------------------------------------------
        try:
            count_logs = _count_rows(
                conn, "scheduler_logs", "ts < ?", [log_cutoff]
            )
            messages.append(
                f"scheduler_logs older than {log_retention_days}d: "
                f"{count_logs} rows"
            )

            if not dry_run and count_logs > 0:
                conn.execute(
                    "DELETE FROM scheduler_logs WHERE ts < ?",
                    [log_cutoff],
                )
                deleted_logs = count_logs
                messages.append(
                    f"  Deleted {deleted_logs} old scheduler_logs."
                )
        except Exception as e:
            # scheduler_logs may not exist in all schema versions
            errors.append(
                f"WARN | scheduler_logs cleanup skipped — {e}"
            )

        # ------------------------------------------------------------------
        # Step 3 — Delete old stopped/paused deployments with no open position
        # Only delete if they have no open position and are old enough
        # ------------------------------------------------------------------
        count_old_deploys = _count_rows(
            conn,
            "deployments",
            "status IN ('stopped', 'paused') "
            "AND open_side IS NULL "
            "AND created_at < ?",
            [deploy_cutoff],
        )

        messages.append(
            f"Old stopped/paused deployments (no position, "
            f">{deployment_retention_days}d): {count_old_deploys} rows"
        )

        if not dry_run and count_old_deploys > 0:
            try:
                # First delete their events to avoid FK constraint
                conn.execute(
                    """
                    DELETE FROM deployment_events
                    WHERE deployment_id IN (
                        SELECT id FROM deployments
                        WHERE status IN ('stopped', 'paused')
                          AND open_side IS NULL
                          AND created_at < ?
                    )
                    """,
                    [deploy_cutoff],
                )
                conn.execute(
                    "DELETE FROM deployments "
                    "WHERE status IN ('stopped', 'paused') "
                    "AND open_side IS NULL "
                    "AND created_at < ?",
                    [deploy_cutoff],
                )
                deleted_deployments = count_old_deploys
                messages.append(
                    f"  Deleted {deleted_deployments} old deployments "
                    f"and their events."
                )
            except Exception as e:
                errors.append(
                    f"ERR | old deployment delete failed — {e}"
                )

        # ------------------------------------------------------------------
        # Step 4 — Current table sizes after cleanup
        # ------------------------------------------------------------------
        total_events   = _count_rows(conn, "deployment_events")
        total_deploys  = _count_rows(conn, "deployments")
        running_deploys= _count_rows(
            conn, "deployments", "status='running'"
        )

        try:
            total_logs = _count_rows(conn, "scheduler_logs")
        except Exception:
            total_logs = 0

        messages.append("")
        messages.append("Table sizes after cleanup:")
        messages.append(f"  deployments       : {total_deploys} rows ({running_deploys} running)")
        messages.append(f"  deployment_events : {total_events} rows")
        messages.append(f"  scheduler_logs    : {total_logs} rows")

    # ------------------------------------------------------------------
    # Step 5 — VACUUM and ANALYZE
    # Must run outside of a transaction (autocommit mode)
    # ------------------------------------------------------------------
    if run_vacuum and not dry_run:
        try:
            db_path = os.getenv("DELTA_BT_DB")
            if not db_path:
                from pathlib import Path
                db_path = str(
                    Path(__file__).resolve().parents[2] / "data" / "delta_bt.sqlite"
                )
            # VACUUM must run outside a transaction
            vacuum_conn = sqlite3.connect(db_path, isolation_level=None)
            vacuum_conn.execute("VACUUM")
            vacuum_conn.execute("ANALYZE")
            vacuum_conn.close()

            size_after = _db_size_mb()
            saved      = size_before - size_after
            messages.append("")
            messages.append(
                f"VACUUM + ANALYZE complete. "
                f"DB size: {size_before:.2f} MB -> {size_after:.2f} MB "
                f"(saved {saved:.2f} MB)"
            )
        except Exception as e:
            errors.append(f"ERR | VACUUM failed — {e}")
    elif dry_run:
        messages.append("")
        messages.append(
            "Dry run — no deletions performed and VACUUM skipped. "
            "Set dry_run=false in params_json to apply changes."
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    summary = (
        f"Cleanup complete — "
        f"events_deleted={deleted_events}, "
        f"logs_deleted={deleted_logs}, "
        f"deployments_deleted={deleted_deployments}"
    )
    messages.insert(
        messages.index("") if "" in messages else len(messages),
        summary,
    )

    if errors:
        messages.append("")
        messages.append("Warnings/Errors:")
        messages.extend(f"  {e}" for e in errors)

    return "### Database Vacuum and Cleanup\n\n" + "\n".join(messages)

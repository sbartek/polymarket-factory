#!/usr/bin/env python3
"""Run SQLite retention cleanup for old operational data."""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.db import DB_PATH, FactoryDB


def format_cleanup_report(result: dict[str, int], retention_days: int, db_path: Path, dry_run: bool) -> str:
    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    verb = "would delete" if dry_run else "deleted"
    header = f"Retention cleanup {'preview' if dry_run else 'run'} for {db_path}"
    lines = [
        header,
        f"Policy: delete rows older than {retention_days} days (before {cutoff})",
    ]
    deleted_items = sorted(
        (key.removesuffix("_deleted"), value)
        for key, value in result.items()
        if key.endswith("_deleted") and not key.startswith(("archives_", "observations_")) and value
    )
    total_deleted = sum(value for _, value in deleted_items)
    if deleted_items:
        lines.append(f"Total rows {verb}: {total_deleted}")
        for table, count in deleted_items:
            lines.append(f"  - {table}: {count}")
    else:
        lines.append(f"No rows {verb}.")
    return "\n".join(lines)


def run_retention_cleanup(db_path: Path, retention_days: int = 730, dry_run: bool = False) -> int:
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    db = FactoryDB(path=db_path)
    mode = "retention_cleanup_dry_run" if dry_run else "retention_cleanup"
    run_id = db.start_run(mode=mode, notes=f"retention_days={retention_days}")
    lock_acquired = False

    try:
        lock_acquired = db.acquire_run_lock("retention_cleanup", run_id, ttl_seconds=3600)
        if not lock_acquired:
            msg = "another retention cleanup already holds the lock"
            print(f"Skip: {msg}")
            db.log_decision(run_id, "run_lock", "skip", reason=msg)
            db.finish_run(run_id, status="aborted", notes=msg)
            return 0

        db.log_decision(run_id, "run_lock", "acquired", reason="retention_cleanup")
        payload = {"retention_days": retention_days, "db_path": str(db_path), "dry_run": dry_run}
        db.log_event(run_id, "info", "retention_cleanup_started", payload=payload)
        result = db.get_retention_cleanup_counts(retention_days=retention_days) if dry_run else db.cleanup_old_snapshots(retention_days=retention_days)
        total_deleted = sum(
            value
            for key, value in result.items()
            if key.endswith("_deleted") and not key.startswith(("archives_", "observations_"))
        )
        db.log_event(
            run_id,
            "info",
            "retention_cleanup_preview" if dry_run else "retention_cleanup_completed",
            payload={**payload, **result, "total_deleted": total_deleted},
        )
        db.finish_run(run_id, status="success", notes=f"total_deleted={total_deleted}")
        print(format_cleanup_report(result, retention_days=retention_days, db_path=db_path, dry_run=dry_run))
        return 0
    except Exception as exc:
        db.log_event(run_id, "error", f"retention_cleanup_failed: {exc}")
        db.finish_run(run_id, status="failed", notes=str(exc))
        raise
    finally:
        if lock_acquired:
            db.release_run_lock("retention_cleanup", run_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DB retention cleanup for old operational tables.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to SQLite DB")
    parser.add_argument("--retention-days", type=int, default=730, help="Delete rows older than this many days")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions without removing rows")
    args = parser.parse_args(argv)
    return run_retention_cleanup(db_path=args.db, retention_days=args.retention_days, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

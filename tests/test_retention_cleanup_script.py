"""Tests for the retention cleanup script entrypoint."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

from factory.db import FactoryDB

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retention_cleanup.py"
_spec = importlib.util.spec_from_file_location("retention_cleanup", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

main = _mod.main
run_retention_cleanup = _mod.run_retention_cleanup


def _insert_archive(db: FactoryDB, run_id: str, created_at: str):
    with db._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO market_snapshot_archives (run_id, source, event_count, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, "fetch_top", 1, "[]", created_at),
        )
        conn.commit()


def _count(db: FactoryDB, table: str) -> int:
    with db._connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_run_retention_cleanup_dry_run_reports_candidates(tmp_path, capsys):
    db_path = tmp_path / "factory.sqlite3"
    db = FactoryDB(path=db_path)
    run_id = db.start_run("paper")
    old = (datetime.now(UTC) - timedelta(days=800)).isoformat(timespec="seconds")
    _insert_archive(db, run_id, old)

    rc = run_retention_cleanup(db_path=db_path, retention_days=730, dry_run=True)

    captured = capsys.readouterr()
    assert rc == 0
    assert "Retention cleanup preview" in captured.out
    assert "market_snapshot_archives: 1" in captured.out
    assert _count(db, "market_snapshot_archives") == 1


def test_main_deletes_rows_and_reports_summary(tmp_path, capsys):
    db_path = tmp_path / "factory.sqlite3"
    db = FactoryDB(path=db_path)
    run_id = db.start_run("paper")
    old = (datetime.now(UTC) - timedelta(days=800)).isoformat(timespec="seconds")
    _insert_archive(db, run_id, old)

    rc = main(["--db", str(db_path), "--retention-days", "730"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Retention cleanup run" in captured.out
    assert "Total rows deleted: 1" in captured.out
    assert "market_snapshot_archives: 1" in captured.out
    assert _count(db, "market_snapshot_archives") == 0


def test_main_returns_error_when_db_missing(tmp_path, capsys):
    db_path = tmp_path / "missing.sqlite3"

    rc = main(["--db", str(db_path)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Database not found" in captured.err

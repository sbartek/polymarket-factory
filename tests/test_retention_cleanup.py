"""Tests for DB retention cleanup of old snapshots and observations."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from factory.db import FactoryDB


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


def _insert_archive(db, run_id: str, created_at: str):
    with db._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO market_snapshot_archives (run_id, source, event_count, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, "fetch_top", 1, '[]', created_at),
        )
        conn.commit()


def _insert_observation(db, run_id: str, created_at: str):
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO market_observations (run_id, market_id, created_at) VALUES (?, ?, ?)",
            (run_id, "mkt-1", created_at),
        )
        conn.commit()


def _count(db, table: str) -> int:
    with db._connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class TestRetentionCleanup:
    def test_deletes_old_archives(self, db):
        run_id = db.start_run("paper")
        old = (datetime.now(UTC) - timedelta(days=800)).isoformat(timespec="seconds")
        recent = datetime.now(UTC).isoformat(timespec="seconds")
        _insert_archive(db, "old-run", old)
        _insert_archive(db, run_id, recent)

        result = db.cleanup_old_snapshots(retention_days=730)

        assert result["archives_deleted"] == 1
        assert _count(db, "market_snapshot_archives") == 1

    def test_deletes_old_observations(self, db):
        run_id = db.start_run("paper")
        old = (datetime.now(UTC) - timedelta(days=800)).isoformat(timespec="seconds")
        recent = datetime.now(UTC).isoformat(timespec="seconds")
        _insert_observation(db, "old-run", old)
        _insert_observation(db, run_id, recent)

        result = db.cleanup_old_snapshots(retention_days=730)

        assert result["observations_deleted"] == 1
        assert _count(db, "market_observations") == 1

    def test_no_op_when_nothing_old(self, db):
        run_id = db.start_run("paper")
        recent = datetime.now(UTC).isoformat(timespec="seconds")
        _insert_archive(db, run_id, recent)
        _insert_observation(db, run_id, recent)

        result = db.cleanup_old_snapshots(retention_days=730)

        assert result["archives_deleted"] == 0
        assert result["observations_deleted"] == 0
        assert _count(db, "market_snapshot_archives") == 1
        assert _count(db, "market_observations") == 1

    def test_custom_retention_days(self, db):
        run_id = db.start_run("paper")
        two_days_ago = (datetime.now(UTC) - timedelta(days=2)).isoformat(timespec="seconds")
        _insert_archive(db, run_id, two_days_ago)

        result = db.cleanup_old_snapshots(retention_days=1)

        assert result["archives_deleted"] == 1

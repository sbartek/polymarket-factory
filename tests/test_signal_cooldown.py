"""Tests for signal cooldown behaviour — covers both traded and alert-only strategies."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from factory.db import FactoryDB


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


def _insert_signal(db: FactoryDB, strategy: str, market_id: str, *,
                   hours_ago: float = 0.5, consumed: bool = False) -> None:
    created_at = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    run_id = "run-test"
    exec_run_id = "run-exec"
    with db._connect() as conn:
        # ensure parent runs exist for FK constraints
        for rid in [run_id, exec_run_id]:
            conn.execute(
                "INSERT OR IGNORE INTO runs (id, started_at, mode, status) VALUES (?,?,?,?)",
                (rid, created_at, "paper", "success"),
            )
        conn.execute(
            """INSERT INTO signals
               (run_id, strategy, market_id, market_title, outcome, market_price,
                p_hat, ev_pp, confidence, created_at, consumed_by_run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, strategy, market_id, "Test Market", "YES", 0.4,
             0.5, 10.0, "medium", created_at, exec_run_id if consumed else None),
        )


class TestHasRecentSignal:
    def test_no_signal_returns_false(self, db):
        assert db.has_recent_signal("ev_news", "market-1") is False

    def test_consumed_signal_within_window_returns_true(self, db):
        _insert_signal(db, "ev_news", "market-1", hours_ago=1.0, consumed=True)
        assert db.has_recent_signal("ev_news", "market-1", hours=24.0) is True

    def test_unconsumed_signal_within_window_returns_true(self, db):
        """Alert-only strategies never consume signals — cooldown must still fire."""
        _insert_signal(db, "fade_certainty_v2", "market-1", hours_ago=1.0, consumed=False)
        assert db.has_recent_signal("fade_certainty_v2", "market-1", hours=24.0) is True

    def test_old_signal_outside_window_returns_false(self, db):
        _insert_signal(db, "ev_news", "market-1", hours_ago=30.0, consumed=True)
        assert db.has_recent_signal("ev_news", "market-1", hours=24.0) is False

    def test_different_strategy_does_not_block(self, db):
        _insert_signal(db, "ev_news", "market-1", hours_ago=1.0, consumed=False)
        assert db.has_recent_signal("stale_market", "market-1", hours=24.0) is False

    def test_different_market_does_not_block(self, db):
        _insert_signal(db, "ev_news", "market-1", hours_ago=1.0, consumed=False)
        assert db.has_recent_signal("ev_news", "market-2", hours=24.0) is False

    def test_custom_cooldown_hours_respected(self, db):
        _insert_signal(db, "fade_certainty_v2", "market-1", hours_ago=50.0, consumed=False)
        assert db.has_recent_signal("fade_certainty_v2", "market-1", hours=72.0) is True
        assert db.has_recent_signal("fade_certainty_v2", "market-1", hours=24.0) is False

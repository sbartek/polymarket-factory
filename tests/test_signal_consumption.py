"""Tests for signal consumption DB methods (get_unconsumed_signals, mark_signals_consumed)."""
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from factory.db import FactoryDB


def _make_db() -> FactoryDB:
    db = FactoryDB(path=Path(tempfile.mktemp(suffix=".sqlite3")))
    return db


def _insert_signal(db: FactoryDB, run_id: str, strategy: str = "test_strat", market_id: str = "test-market",
                   outcome: str = "YES", ev_pp: float = 10.0, phase: str = "scan",
                   created_at: str | None = None):
    """Insert a signal directly for testing."""
    from factory.db import utcnow
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO signals (run_id, strategy, market_id, market_title, outcome, market_price, p_hat, ev_pp, confidence, closes, url, rationale, time_window, edge_type, decision_status, phase, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, strategy, market_id, f"Test {market_id}", outcome, 0.5, 0.6, ev_pp, "high", "2026-04-10", "", "", "short", "other", "generated", phase, created_at or utcnow()),
        )
        conn.commit()


class TestGetUnconsumedSignals:
    def test_returns_fresh_scan_signals(self):
        db = _make_db()
        run_id = db.start_run(mode="paper_scan")
        _insert_signal(db, run_id, market_id="m1")
        _insert_signal(db, run_id, market_id="m2")

        rows = db.get_unconsumed_signals(max_age_hours=2.0)
        assert len(rows) == 2

    def test_excludes_stale_signals(self):
        db = _make_db()
        run_id = db.start_run(mode="paper_scan")
        old_time = (datetime.now(UTC) - timedelta(hours=3)).isoformat(timespec="seconds")
        _insert_signal(db, run_id, market_id="old", created_at=old_time)
        _insert_signal(db, run_id, market_id="fresh")

        rows = db.get_unconsumed_signals(max_age_hours=2.0)
        assert len(rows) == 1
        assert rows[0]["market_id"] == "fresh"

    def test_excludes_consumed_signals(self):
        db = _make_db()
        run_id = db.start_run(mode="paper_scan")
        _insert_signal(db, run_id, market_id="m1")

        rows = db.get_unconsumed_signals()
        assert len(rows) == 1
        db.mark_signals_consumed([rows[0]["id"]], "exec-run-1")

        rows2 = db.get_unconsumed_signals()
        assert len(rows2) == 0

    def test_excludes_combined_phase_signals(self):
        db = _make_db()
        run_id = db.start_run(mode="paper")
        _insert_signal(db, run_id, market_id="m1", phase="combined")

        rows = db.get_unconsumed_signals()
        assert len(rows) == 0

    def test_deduplicates_by_strategy_market_outcome(self):
        db = _make_db()
        run1 = db.start_run(mode="paper_scan")
        run2 = db.start_run(mode="paper_scan")
        _insert_signal(db, run1, market_id="m1", ev_pp=5.0)
        _insert_signal(db, run2, market_id="m1", ev_pp=8.0)  # newer, same market

        rows = db.get_unconsumed_signals()
        assert len(rows) == 1
        assert rows[0]["ev_pp"] == 8.0  # most recent wins


class TestMarkSignalsConsumed:
    def test_marks_multiple_signals(self):
        db = _make_db()
        run_id = db.start_run(mode="paper_scan")
        _insert_signal(db, run_id, market_id="m1")
        _insert_signal(db, run_id, market_id="m2")

        rows = db.get_unconsumed_signals()
        ids = [r["id"] for r in rows]
        db.mark_signals_consumed(ids, "exec-run")

        remaining = db.get_unconsumed_signals()
        assert len(remaining) == 0

    def test_noop_on_empty_list(self):
        db = _make_db()
        db.mark_signals_consumed([], "exec-run")  # should not raise

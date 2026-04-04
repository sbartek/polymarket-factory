"""Tests for the execute-only phase of the runner."""
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from factory.db import FactoryDB
from factory.runner import run, _reconstruct_signal
from factory.models import Signal


def _make_db() -> FactoryDB:
    return FactoryDB(path=Path(tempfile.mktemp(suffix=".sqlite3")))


def _insert_scan_signal(db: FactoryDB, run_id: str, strategy: str = "spread_arb",
                        market_id: str = "test-event", outcome: str = "YES",
                        ev_pp: float = 10.0, created_at: str | None = None):
    from factory.db import utcnow
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO signals (run_id, strategy, market_id, market_title, outcome, market_price, p_hat, ev_pp, confidence, closes, url, rationale, time_window, edge_type, decision_status, phase, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, strategy, market_id, f"Test {market_id}", outcome, 0.40, 0.55, ev_pp, "high", "2026-05-15", "https://polymarket.com/event/test", "", "short", "other", "generated", "scan", created_at or utcnow()),
        )
        conn.commit()


class TestReconstructSignal:
    def test_reconstructs_from_db_row(self):
        row = {
            "strategy": "spread_arb",
            "market_id": "test-event",
            "market_title": "Test event",
            "outcome": "YES",
            "market_price": 0.40,
            "p_hat": 0.55,
            "ev_pp": 15.0,
            "confidence": "high",
            "closes": "2026-05-15",
            "url": "https://polymarket.com/event/test",
            "rationale": "arb-basket",
        }
        sig = _reconstruct_signal(row)
        assert isinstance(sig, Signal)
        assert sig.strategy == "spread_arb"
        assert sig.ev_pp == 15.0
        assert sig.outcome == "YES"


class TestExecutePhase:
    @patch("factory.runner.fetch_top", return_value=[])
    @patch("factory.runner.send_whatsapp", return_value=True)
    @patch("factory.runner.fetch_closed", return_value=[])
    def test_handles_zero_cached_signals(self, _fc, _wa, _ft):
        """Execute phase with no cached signals should complete gracefully."""
        db = _make_db()
        with patch("factory.runner.FactoryDB", return_value=db):
            run(environment="paper", dry_run=True, send=False, phase="execute")

    @patch("factory.runner.fetch_top", return_value=[])
    @patch("factory.runner.send_whatsapp", return_value=True)
    @patch("factory.runner.fetch_closed", return_value=[])
    def test_consumes_fresh_signals(self, _fc, _wa, _ft):
        db = _make_db()
        scan_run = db.start_run(mode="paper_scan")
        _insert_scan_signal(db, scan_run, market_id="m1")
        _insert_scan_signal(db, scan_run, market_id="m2")

        with patch("factory.runner.FactoryDB", return_value=db):
            run(environment="paper", dry_run=True, send=False, phase="execute")

        # Signals should be marked as consumed
        remaining = db.get_unconsumed_signals()
        assert len(remaining) == 0

    @patch("factory.runner.fetch_top", return_value=[])
    @patch("factory.runner.send_whatsapp", return_value=True)
    @patch("factory.runner.fetch_closed", return_value=[])
    def test_skips_stale_signals(self, _fc, _wa, _ft):
        db = _make_db()
        scan_run = db.start_run(mode="paper_scan")
        old_time = (datetime.now(UTC) - timedelta(hours=3)).isoformat(timespec="seconds")
        _insert_scan_signal(db, scan_run, market_id="stale", created_at=old_time)
        _insert_scan_signal(db, scan_run, market_id="fresh")

        with patch("factory.runner.FactoryDB", return_value=db):
            run(environment="paper", dry_run=True, send=False, phase="execute")

        # Only fresh signal consumed, stale one stays unconsumed but not returned
        # (it's filtered by TTL in get_unconsumed_signals)
        with db._connect() as conn:
            stale_row = conn.execute(
                "SELECT consumed_by_run_id FROM signals WHERE market_id = 'stale'"
            ).fetchone()
            assert stale_row["consumed_by_run_id"] is None

            fresh_row = conn.execute(
                "SELECT consumed_by_run_id FROM signals WHERE market_id = 'fresh'"
            ).fetchone()
            assert fresh_row["consumed_by_run_id"] is not None

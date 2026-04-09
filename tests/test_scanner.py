"""Tests for factory.scanner (Phase 1 scan)."""
import signal
import tempfile
from unittest.mock import patch, MagicMock

from factory.db import FactoryDB
from factory.models import Signal
from factory.scanner import scan


def _fake_market(slug="test-event", yes_price=0.50):
    return {
        "slug": slug,
        "title": f"Will {slug} happen?",
        "volume24hr": 100_000,
        "endDate": "2026-05-15",
        "markets": [{
            "id": "m1",
            "question": f"Will {slug} happen?",
            "outcomePrices": f'[{yes_price},{1-yes_price}]',
            "closed": False,
        }],
    }


def _fake_signal(strategy="test_strat", slug="test-event"):
    return Signal(
        strategy=strategy,
        market_id=slug,
        market_title=f"Will {slug} happen?",
        outcome="YES",
        market_price=0.50,
        p_hat=0.65,
        ev_pp=15.0,
        confidence="high",
        closes="2026-05-15",
        url=f"https://polymarket.com/event/{slug}",
    )


class TestScanner:
    @patch("factory.scanner.fetch_top_paginated", return_value=[_fake_market()])
    @patch("factory.scanner.STRATEGIES", [])
    def test_scan_caches_no_signals_when_no_strategies(self, _mock_fetch):
        with patch("factory.scanner.FactoryDB") as MockDB:
            db = MagicMock()
            MockDB.return_value = db
            db.start_run.return_value = "run-1"
            db.acquire_run_lock.return_value = True

            scan(environment="paper", market_limit=50)

            db.start_run.assert_called_once()
            db.log_market_snapshot_archive.assert_called_once()
            # No signals logged
            db.log_signal.assert_not_called()

    @patch("factory.scanner.fetch_top_paginated", return_value=[_fake_market()])
    def test_scan_caches_signals_with_scan_phase(self, _mock_fetch):
        with patch("factory.scanner.FactoryDB") as MockDB:
            db = MagicMock()
            MockDB.return_value = db
            db.start_run.return_value = "run-1"
            db.acquire_run_lock.return_value = True

            fake_strat = MagicMock()
            fake_strat.name = "test_strat"
            fake_strat.paused = False
            fake_strat.signal_cooldown_hours = 24.0
            fake_strat.scan.return_value = [_fake_signal()]
            fake_strat.last_check_details = []
            fake_strat.last_basket_details = []
            db.has_recent_signal.return_value = False

            with patch("factory.scanner.STRATEGIES", [fake_strat]):
                with patch("factory.scanner.strategy_metadata", return_value={
                    "test_strat": {"edge_type": "other", "time_window": "short", "paused": False}
                }):
                    with patch("factory.scanner.should_run_in_cycle", return_value=True):
                        scan(environment="paper", market_limit=50)

            # Verify signal was logged with phase='scan'
            db.log_signal.assert_called_once()
            call_kwargs = db.log_signal.call_args
            assert call_kwargs[1]["phase"] == "scan"
            assert call_kwargs[1]["decision_status"] == "generated"

    @patch("factory.scanner.fetch_top_paginated", return_value=[_fake_market()])
    def test_scan_does_not_touch_broker(self, _mock_fetch):
        """Scanner should never import or use PaperBroker."""
        with patch("factory.scanner.FactoryDB") as MockDB:
            db = MagicMock()
            MockDB.return_value = db
            db.start_run.return_value = "run-1"
            db.acquire_run_lock.return_value = True

            with patch("factory.scanner.STRATEGIES", []):
                scan(environment="paper", market_limit=50)

            # No broker-related calls
            for call in db.method_calls:
                assert "open_position" not in call[0]
                assert "close_position" not in call[0]

    @patch("factory.scanner.fetch_top_paginated")
    def test_scan_aborts_when_lock_held(self, mock_fetch):
        with patch("factory.scanner.FactoryDB") as MockDB:
            db = MagicMock()
            MockDB.return_value = db
            db.start_run.return_value = "run-1"
            db.acquire_run_lock.return_value = False

            scan(environment="paper", market_limit=50)

            mock_fetch.assert_not_called()
            db.finish_run.assert_called_once()
            assert "aborted" in str(db.finish_run.call_args)

    @patch("factory.scanner.fetch_top_paginated", return_value=[_fake_market()])
    def test_scan_marks_run_failed_on_sigterm(self, _mock_fetch):
        handlers = {}

        def fake_signal(sig, handler):
            previous = handlers.get(sig, signal.SIG_DFL)
            handlers[sig] = handler
            return previous

        with patch("factory.scanner.FactoryDB") as MockDB, \
             patch("factory.scanner.signal.signal", side_effect=fake_signal), \
             patch("factory.scanner.build_market_index", side_effect=lambda markets: handlers[signal.SIGTERM](signal.SIGTERM, None)):
            db = MagicMock()
            MockDB.return_value = db
            db.start_run.return_value = "run-1"
            db.acquire_run_lock.return_value = True

            with patch("factory.scanner.STRATEGIES", []):
                try:
                    scan(environment="paper", market_limit=50)
                except SystemExit as exc:
                    assert exc.code == 128 + signal.SIGTERM
                else:
                    raise AssertionError("scan() should exit on SIGTERM")

            db.finish_run.assert_called_once()
            assert db.finish_run.call_args.kwargs["status"] == "failed"
            assert "SIGTERM" in db.finish_run.call_args.kwargs["notes"]

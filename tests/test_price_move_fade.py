"""Tests for the price_move_fade strategy."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import date, datetime, timedelta, UTC

from factory.db import FactoryDB
from factory.strategies.price_move_fade import PriceMoveFadeStrategy, _days_to_close


def _make_db():
    db = FactoryDB(path=Path(tempfile.mktemp(suffix=".db")))
    # Create a valid run for FK constraints
    db._test_run_id = db.start_run("paper")
    return db


def _insert_observation(db, market_id, yes_price, volume, close_time, created_at, title="Test market"):
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO market_observations
               (run_id, event_slug, market_id, market_slug, market_title,
                yes_price, best_bid, best_ask, spread, liquidity, volume, volume_24hr,
                close_time, created_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, NULL, ?, ?)""",
            (db._test_run_id, market_id, market_id, market_id, title,
             yes_price, volume, close_time, created_at),
        )
        conn.commit()


class TestDaysToClose:
    def test_valid_date(self):
        future = (date.today() + timedelta(days=5)).isoformat()
        assert _days_to_close(future) == 5

    def test_none(self):
        assert _days_to_close(None) is None

    def test_invalid(self):
        assert _days_to_close("not-a-date") is None


class TestPriceMoveFade:
    def test_detects_upward_move_and_fades_with_no(self):
        """Large upward price move should produce a NO signal (fade the rise)."""
        db = _make_db()
        close_date = (date.today() + timedelta(days=3)).isoformat()
        now = datetime.now(UTC)
        t1 = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        t2 = now.isoformat(timespec="seconds")
        _insert_observation(db, "test-market", 0.40, 10000, close_date, t1)
        _insert_observation(db, "test-market", 0.60, 10000, close_date, t2)

        s = PriceMoveFadeStrategy()
        with patch("factory.strategies.price_move_fade.FactoryDB", return_value=db):
            signals = s.scan([])

        assert len(signals) == 1
        assert signals[0].outcome == "NO"
        assert signals[0].ev_pp > 0

    def test_detects_downward_move_and_fades_with_yes(self):
        """Large downward price move should produce a YES signal (fade the drop)."""
        db = _make_db()
        close_date = (date.today() + timedelta(days=3)).isoformat()
        now = datetime.now(UTC)
        t1 = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        t2 = now.isoformat(timespec="seconds")
        _insert_observation(db, "test-market", 0.60, 10000, close_date, t1)
        _insert_observation(db, "test-market", 0.40, 10000, close_date, t2)

        s = PriceMoveFadeStrategy()
        with patch("factory.strategies.price_move_fade.FactoryDB", return_value=db):
            signals = s.scan([])

        assert len(signals) == 1
        assert signals[0].outcome == "YES"

    def test_ignores_small_move(self):
        """Moves below threshold should not generate signals."""
        db = _make_db()
        close_date = (date.today() + timedelta(days=3)).isoformat()
        now = datetime.now(UTC)
        t1 = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        t2 = now.isoformat(timespec="seconds")
        _insert_observation(db, "test-market", 0.50, 10000, close_date, t1)
        _insert_observation(db, "test-market", 0.55, 10000, close_date, t2)

        s = PriceMoveFadeStrategy()
        with patch("factory.strategies.price_move_fade.FactoryDB", return_value=db):
            signals = s.scan([])

        assert len(signals) == 0

    def test_ignores_long_dated_market(self):
        """Markets closing > 7 days out should be skipped."""
        db = _make_db()
        close_date = (date.today() + timedelta(days=30)).isoformat()
        now = datetime.now(UTC)
        t1 = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        t2 = now.isoformat(timespec="seconds")
        _insert_observation(db, "test-market", 0.40, 10000, close_date, t1)
        _insert_observation(db, "test-market", 0.60, 10000, close_date, t2)

        s = PriceMoveFadeStrategy()
        with patch("factory.strategies.price_move_fade.FactoryDB", return_value=db):
            signals = s.scan([])

        assert len(signals) == 0

    def test_ignores_low_volume(self):
        """Markets with low volume should be skipped."""
        db = _make_db()
        close_date = (date.today() + timedelta(days=3)).isoformat()
        now = datetime.now(UTC)
        t1 = (now - timedelta(hours=2)).isoformat(timespec="seconds")
        t2 = now.isoformat(timespec="seconds")
        _insert_observation(db, "test-market", 0.40, 1000, close_date, t1)
        _insert_observation(db, "test-market", 0.60, 1000, close_date, t2)

        s = PriceMoveFadeStrategy()
        with patch("factory.strategies.price_move_fade.FactoryDB", return_value=db):
            signals = s.scan([])

        assert len(signals) == 0

    def test_is_alert_only(self):
        s = PriceMoveFadeStrategy()
        assert s.alert_only is True
        assert s.promotable is True

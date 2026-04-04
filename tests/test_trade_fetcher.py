"""Tests for the CLOB trade data pipeline."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from factory.db import FactoryDB
from factory.trade_fetcher import fetch_trades, _fetch_page


def _make_db():
    return FactoryDB(path=Path(tempfile.mktemp(suffix=".db")))


def _sample_trade(ts=1775322000, slug="test-market", price=0.65, size=10.0, tx_hash="0xabc123"):
    return {
        "conditionId": "0xcond1",
        "slug": slug,
        "eventSlug": "test-event",
        "title": "Test Market",
        "outcome": "Yes",
        "side": "BUY",
        "price": price,
        "size": size,
        "timestamp": ts,
        "transactionHash": tx_hash,
    }


class TestLogMarketTrades:
    def test_insert_trades(self):
        db = _make_db()
        run_id = db.start_run(mode="test")
        trades = [_sample_trade(tx_hash="0x1"), _sample_trade(tx_hash="0x2")]
        inserted = db.log_market_trades(run_id, trades)
        assert inserted == 2

    def test_dedup_by_tx_hash(self):
        db = _make_db()
        run_id = db.start_run(mode="test")
        trade = _sample_trade(tx_hash="0xdup")
        db.log_market_trades(run_id, [trade])
        inserted = db.log_market_trades(run_id, [trade])
        # Second insert should be ignored (duplicate tx_hash)
        with db._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM market_trades WHERE tx_hash = '0xdup'"
            ).fetchone()[0]
        assert count == 1

    def test_empty_input(self):
        db = _make_db()
        run_id = db.start_run(mode="test")
        assert db.log_market_trades(run_id, []) == 0


class TestGetLatestTradeTimestamp:
    def test_empty_table(self):
        db = _make_db()
        assert db.get_latest_trade_timestamp() == 0

    def test_returns_max(self):
        db = _make_db()
        run_id = db.start_run(mode="test")
        db.log_market_trades(run_id, [
            _sample_trade(ts=100, tx_hash="0xa"),
            _sample_trade(ts=300, tx_hash="0xb"),
            _sample_trade(ts=200, tx_hash="0xc"),
        ])
        assert db.get_latest_trade_timestamp() == 300


class TestGetTradeVolumeBySlug:
    def test_volume_aggregation(self):
        db = _make_db()
        run_id = db.start_run(mode="test")
        import time
        now_ts = int(time.time())
        db.log_market_trades(run_id, [
            _sample_trade(ts=now_ts - 100, slug="mkt-a", size=10.0, price=0.5, tx_hash="0x1"),
            _sample_trade(ts=now_ts - 50, slug="mkt-a", size=20.0, price=0.6, tx_hash="0x2"),
            _sample_trade(ts=now_ts - 30, slug="mkt-b", size=100.0, price=0.9, tx_hash="0x3"),
        ])
        vol = db.get_trade_volume_by_slug("mkt-a", since_hours=1.0)
        assert vol["trade_count"] == 2
        assert vol["total_size"] == 30.0

    def test_no_trades(self):
        db = _make_db()
        vol = db.get_trade_volume_by_slug("nonexistent")
        assert vol["trade_count"] == 0


class TestGetHourlyTradeVolume:
    def test_hourly_buckets(self):
        db = _make_db()
        run_id = db.start_run(mode="test")
        import time
        now_ts = int(time.time())
        hour_ago = now_ts - 3600
        db.log_market_trades(run_id, [
            _sample_trade(ts=hour_ago + 10, slug="mkt", size=5.0, tx_hash="0x1"),
            _sample_trade(ts=hour_ago + 20, slug="mkt", size=15.0, tx_hash="0x2"),
            _sample_trade(ts=now_ts - 10, slug="mkt", size=25.0, tx_hash="0x3"),
        ])
        buckets = db.get_hourly_trade_volume("mkt", hours=2)
        assert len(buckets) >= 1  # at least one bucket


class TestFetchTrades:
    @patch("factory.trade_fetcher._fetch_page")
    def test_incremental_fetch(self, mock_page):
        db = _make_db()
        # First page returns 2 trades, second page empty (end)
        mock_page.side_effect = [
            [_sample_trade(ts=100, tx_hash="0x1"), _sample_trade(ts=200, tx_hash="0x2")],
            [],
        ]
        fetched, inserted = fetch_trades(total_limit=5000, db=db)
        assert fetched == 2
        assert inserted == 2
        assert db.get_latest_trade_timestamp() == 200

    @patch("factory.trade_fetcher._fetch_page")
    def test_respects_total_limit(self, mock_page):
        db = _make_db()
        mock_page.return_value = [_sample_trade(ts=i, tx_hash=f"0x{i}") for i in range(100, 103)]
        fetched, inserted = fetch_trades(total_limit=3, db=db)
        assert fetched == 3

    @patch("factory.trade_fetcher._fetch_page")
    def test_handles_fetch_failure(self, mock_page):
        db = _make_db()
        mock_page.side_effect = Exception("API down")
        fetched, inserted = fetch_trades(total_limit=100, db=db)
        assert fetched == 0
        assert inserted == 0

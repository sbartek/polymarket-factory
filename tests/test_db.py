"""Unit tests for factory/db.py — run lock and CSV import behaviour."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from factory.db import FactoryDB


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


# ---------------------------------------------------------------------------
# Run-lock tests
# ---------------------------------------------------------------------------

class TestRunLock:
    def test_acquire_new_lock(self, db):
        assert db.acquire_run_lock("main", "run1") is True

    def test_same_owner_reacquires(self, db):
        db.acquire_run_lock("main", "run1")
        assert db.acquire_run_lock("main", "run1") is True

    def test_different_owner_blocked(self, db):
        db.acquire_run_lock("main", "run1")
        assert db.acquire_run_lock("main", "run2") is False

    def test_release_allows_new_owner(self, db):
        db.acquire_run_lock("main", "run1")
        db.release_run_lock("main", "run1")
        assert db.acquire_run_lock("main", "run2") is True

    def test_release_by_wrong_owner_is_noop(self, db):
        db.acquire_run_lock("main", "run1")
        db.release_run_lock("main", "run99")  # wrong owner — should not release
        assert db.acquire_run_lock("main", "run2") is False

    def test_expired_lock_can_be_acquired_by_new_owner(self, db):
        db.acquire_run_lock("main", "run1", ttl_seconds=-1)  # expires immediately
        assert db.acquire_run_lock("main", "run2") is True

    def test_independent_lock_names_do_not_interfere(self, db):
        db.acquire_run_lock("main", "run1")
        assert db.acquire_run_lock("secondary", "run2") is True


# ---------------------------------------------------------------------------
# CSV-import tests
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "id", "strategy", "market_id", "market_title", "outcome",
    "amount_usdc", "entry_price", "shares", "opened_at", "closes",
    "url", "status", "exit_price", "closed_at", "pnl_usdc",
    "resolved_outcome", "notes",
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _sample_row(**overrides) -> dict:
    base = {
        "id": "t1", "strategy": "ev_news", "market_id": "m1",
        "market_title": "Will it rain?", "outcome": "YES",
        "amount_usdc": "10.0", "entry_price": "0.5", "shares": "20.0",
        "opened_at": "2026-01-01T00:00:00", "closes": "", "url": "",
        "status": "open", "exit_price": "0", "closed_at": "",
        "pnl_usdc": "0", "resolved_outcome": "", "notes": "",
    }
    base.update(overrides)
    return base


class TestBackfillTradeMetadata:
    def test_backfills_missing_trade_metadata_from_strategy_defaults(self, db):
        db.insert_trade({
            "id": "legacy1", "strategy": "ev_news", "market_id": "m1", "market_title": "T",
            "outcome": "YES", "amount_usdc": 10.0, "entry_price": 0.5, "shares": 20.0,
            "opened_at": "2026-01-01T00:00:00", "status": "open",
        })
        updated = db.backfill_trade_metadata()
        assert updated == 1
        row = db.load_trades()[0]
        assert row["lifecycle_group"] == "active"
        assert row["time_window"] == "medium"
        assert row["edge_type"] == "information"

    def test_preserves_existing_trade_metadata(self, db):
        db.insert_trade({
            "id": "legacy2", "strategy": "fade_certainty", "market_id": "m2", "market_title": "T2",
            "outcome": "YES", "amount_usdc": 10.0, "entry_price": 0.5, "shares": 20.0,
            "opened_at": "2026-01-01T00:00:00", "status": "open",
            "lifecycle_group": "legacy", "time_window": "long", "edge_type": "other",
        })
        updated = db.backfill_trade_metadata()
        assert updated == 0
        row = db.load_trades()[0]
        assert row["lifecycle_group"] == "legacy"
        assert row["time_window"] == "long"
        assert row["edge_type"] == "other"


class TestCsvImport:
    def test_imports_rows_from_csv(self, tmp_path, db):
        csv_path = tmp_path / "trades.csv"
        _write_csv(csv_path, [_sample_row()])

        count = db.ensure_trades_imported_from_csv(csv_path)

        assert count == 1
        trades = db.load_trades()
        assert len(trades) == 1
        assert trades[0]["id"] == "t1"
        assert trades[0]["strategy"] == "ev_news"
        assert trades[0]["amount_usdc"] == pytest.approx(10.0)

    def test_imports_multiple_rows(self, tmp_path, db):
        csv_path = tmp_path / "trades.csv"
        _write_csv(csv_path, [
            _sample_row(id="t1"),
            _sample_row(id="t2", market_id="m2"),
        ])

        count = db.ensure_trades_imported_from_csv(csv_path)

        assert count == 2
        assert len(db.load_trades()) == 2

    def test_skips_import_if_table_already_has_rows(self, tmp_path, db):
        db.insert_trade({
            "id": "existing", "strategy": "s", "market_id": "m",
            "market_title": "T", "outcome": "YES", "amount_usdc": 5.0,
            "entry_price": 0.5, "shares": 10.0,
            "opened_at": "2026-01-01T00:00:00", "status": "open",
        })
        csv_path = tmp_path / "trades.csv"
        _write_csv(csv_path, [_sample_row(id="t2")])

        count = db.ensure_trades_imported_from_csv(csv_path)

        assert count == 0
        assert len(db.load_trades()) == 1  # only the pre-existing row

    def test_returns_zero_if_csv_missing(self, tmp_path, db):
        count = db.ensure_trades_imported_from_csv(tmp_path / "nonexistent.csv")
        assert count == 0

    def test_second_call_is_idempotent(self, tmp_path, db):
        csv_path = tmp_path / "trades.csv"
        _write_csv(csv_path, [_sample_row()])
        db.ensure_trades_imported_from_csv(csv_path)

        count2 = db.ensure_trades_imported_from_csv(csv_path)

        assert count2 == 0
        assert len(db.load_trades()) == 1


class TestMarketObservations:
    def test_logs_market_observations(self, db):
        run_id = db.start_run("paper")

        db.log_market_observations(run_id, [
            {
                "event_slug": "event-a",
                "market_id": "event-a:123",
                "market_slug": "market-a",
                "market_title": "Example market",
                "yes_price": 0.42,
                "best_bid": 0.4,
                "best_ask": 0.44,
                "spread": 0.04,
                "liquidity": 120.0,
                "volume": 2500.0,
                "volume_24hr": 400.0,
                "close_time": "2026-04-10T00:00:00Z",
            }
        ])

        with db._connect() as conn:
            row = conn.execute(
                "SELECT market_id, market_title, yes_price, best_bid, best_ask, volume_24hr FROM market_observations"
            ).fetchone()

        assert row is not None
        assert row["market_id"] == "event-a:123"
        assert row["market_title"] == "Example market"
        assert row["yes_price"] == pytest.approx(0.42)
        assert row["best_bid"] == pytest.approx(0.4)
        assert row["best_ask"] == pytest.approx(0.44)
        assert row["volume_24hr"] == pytest.approx(400.0)

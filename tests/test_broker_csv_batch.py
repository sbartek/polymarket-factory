"""Tests for PaperBroker — pure SQLite, no CSV."""
from __future__ import annotations

import pytest

from factory.broker import PaperBroker
from factory.db import FactoryDB
from factory.models import Signal


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


def _make_signal(market_id: str = "mkt-1") -> Signal:
    return Signal(
        strategy="test_strat",
        market_id=market_id,
        market_title="Test Market",
        outcome="YES",
        market_price=0.5,
        p_hat=0.7,
        ev_pp=20.0,
        confidence="high",
        closes="2026-12-31",
        url="https://example.com",
    )


class TestPaperBroker:
    def test_open_position_persists_to_db(self, db):
        broker = PaperBroker(db=db)
        trade = broker.open_position(_make_signal(), 10.0)
        assert trade.strategy == "test_strat"
        assert broker.has_position("mkt-1", "test_strat")

    def test_close_position_updates_db(self, db):
        broker = PaperBroker(db=db)
        trade = broker.open_position(_make_signal(), 10.0)
        broker.close_position(trade.id, "YES")
        assert len(broker.get_open_positions()) == 0

    def test_no_csv_attribute(self, db):
        broker = PaperBroker(db=db)
        assert not hasattr(broker, "export_csv")
        assert not hasattr(broker, "_csv_dirty")

"""Tests for auto-closing PARTIAL_YES_UNHEDGED positions in LiveBroker."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from factory.db import FactoryDB
from factory.live_broker import LiveBroker


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


def _insert_unhedged_trade(db: FactoryDB, trade_id: str = "unhedged-1", market_id: str = "test-event:123"):
    run_id = db.start_run("live")
    db.insert_trade({
        "id": trade_id,
        "strategy": "carry_rewards",
        "market_id": market_id,
        "market_title": "Test Market",
        "outcome": "PARTIAL_YES_UNHEDGED",
        "amount_usdc": 10.0,
        "entry_price": 0.5,
        "shares": 20.0,
        "opened_at": "2026-04-04T10:00:00",
        "closes": "2026-12-31",
        "url": "https://example.com",
        "status": "open",
        "exit_price": 0,
        "closed_at": "",
        "pnl_usdc": 0,
        "resolved_outcome": "",
        "notes": "UNHEDGED:yes_only,clob_id=abc123,no_failed",
        "run_id_opened": run_id,
        "lifecycle_group": "active",
        "time_window": "medium",
        "edge_type": "structural",
        "mode": "live",
    })
    return run_id


class TestTryCloseUnhedged:
    def test_sells_yes_tokens_and_closes_trade(self, db):
        run_id = _insert_unhedged_trade(db)
        broker = LiveBroker(db=db, run_id=run_id)

        trade = broker.get_open_positions()[0]
        market_index = {
            "test-event:123": {
                "market": {"clobTokenIds": '["yes-token-id", "no-token-id"]'},
                "event": {},
            }
        }

        with patch("factory.live_broker.clob_api.place_market_order", return_value={"orderID": "sell-order-1"}), \
             patch("factory.live_broker.clob_api.get_clob_token_ids", return_value=("yes-token-id", "no-token-id")):
            result = broker.try_close_unhedged(trade, market_index)

        assert result is True
        open_positions = broker.get_open_positions()
        assert len(open_positions) == 0

    def test_returns_false_for_non_unhedged_trade(self, db):
        run_id = db.start_run("live")
        broker = LiveBroker(db=db, run_id=run_id)
        trade = {"id": "t1", "notes": "normal trade", "outcome": "YES"}

        result = broker.try_close_unhedged(trade, {})
        assert result is False

    def test_returns_false_when_no_market_data(self, db):
        run_id = _insert_unhedged_trade(db)
        broker = LiveBroker(db=db, run_id=run_id)
        trade = broker.get_open_positions()[0]

        result = broker.try_close_unhedged(trade, {})
        assert result is False

    def test_returns_false_when_sell_fails(self, db):
        run_id = _insert_unhedged_trade(db)
        broker = LiveBroker(db=db, run_id=run_id)
        trade = broker.get_open_positions()[0]

        market_index = {
            "test-event:123": {
                "market": {"clobTokenIds": '["yes-token-id", "no-token-id"]'},
                "event": {},
            }
        }

        with patch("factory.live_broker.clob_api.place_market_order", side_effect=Exception("CLOB down")), \
             patch("factory.live_broker.clob_api.get_clob_token_ids", return_value=("yes-token-id", "no-token-id")):
            result = broker.try_close_unhedged(trade, market_index)

        assert result is False
        # Trade should still be open
        assert len(broker.get_open_positions()) == 1

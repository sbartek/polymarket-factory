"""Tests for live executor slippage guard and order processing."""
from unittest.mock import patch, MagicMock

from factory.db import FactoryDB
from factory.live_executor import execute_pending_orders


def _enqueue_order(db, strategy="price_move_fade", outcome="YES", market_price=0.30,
                   amount=1.0, market_id="test-slug:123", token_id="tok123"):
    from factory.models import Signal
    sig = Signal(
        strategy=strategy, market_id=market_id, market_title="Test Market?",
        outcome=outcome, market_price=market_price, p_hat=0.5, ev_pp=20.0,
        confidence="medium", closes="2026-05-01", url="", rationale="test",
    )
    db.enqueue_live_order("run1", sig, amount, token_id)


def test_slippage_guard_skips_bad_entry(tmp_path):
    """Order should be skipped when current price is >10pp worse than signal."""
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    _enqueue_order(db, outcome="YES", market_price=0.30, market_id="test-slug:123")

    # Mock fetch_by_slug to return market with current YES price = 0.50 (20pp worse)
    mock_event = {
        "markets": [{"id": "123", "outcomePrices": '["0.50", "0.50"]'}]
    }
    with patch("factory.live_executor.place_market_order") as mock_place, \
         patch("factory.feed.fetch_by_slug", return_value=[mock_event]):
        count = execute_pending_orders(db)

    assert count == 0, "Should skip due to slippage"
    mock_place.assert_not_called()
    # Check order was marked as skipped
    orders = db.get_pending_live_orders()
    assert len(orders) == 0  # no longer pending


def test_slippage_guard_allows_good_entry(tmp_path):
    """Order should proceed when slippage is within threshold."""
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    _enqueue_order(db, outcome="YES", market_price=0.30, market_id="test-slug:123",
                   token_id="full_token_id_here")

    # Current YES price = 0.32 (only 2pp worse — acceptable)
    mock_event = {
        "markets": [{"id": "123", "outcomePrices": '["0.32", "0.68"]'}]
    }
    mock_resp = {"orderID": "0xabc", "success": True}
    with patch("factory.live_executor.place_market_order", return_value=mock_resp) as mock_place, \
         patch("factory.feed.fetch_by_slug", return_value=[mock_event]), \
         patch("factory.live_executor.send_notification"):
        count = execute_pending_orders(db)

    assert count == 1, "Should execute — slippage within threshold"
    mock_place.assert_called_once()


def test_slippage_guard_no_outcome(tmp_path):
    """NO outcome: slippage computed on NO price (1 - YES price)."""
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    # Signal: YES=0.20, so NO=0.80. We're buying NO at 0.80.
    _enqueue_order(db, outcome="NO", market_price=0.20, market_id="test-slug:456")

    # Current YES=0.05, so NO=0.95. That's 15pp worse for NO buyer (0.95 vs 0.80).
    mock_event = {
        "markets": [{"id": "456", "outcomePrices": '["0.05", "0.95"]'}]
    }
    with patch("factory.live_executor.place_market_order") as mock_place, \
         patch("factory.feed.fetch_by_slug", return_value=[mock_event]):
        count = execute_pending_orders(db)

    assert count == 0, "Should skip — NO price moved 15pp worse"
    mock_place.assert_not_called()


def test_slippage_check_failure_proceeds(tmp_path):
    """If slippage check fails (API error), order should still proceed."""
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    _enqueue_order(db, outcome="YES", market_price=0.30, market_id="test-slug:789",
                   token_id="full_token")

    mock_resp = {"orderID": "0xdef", "success": True}
    with patch("factory.live_executor.place_market_order", return_value=mock_resp) as mock_place, \
         patch("factory.feed.fetch_by_slug", side_effect=Exception("API down")), \
         patch("factory.live_executor.send_notification"):
        count = execute_pending_orders(db)

    assert count == 1, "Should proceed despite slippage check failure"
    mock_place.assert_called_once()

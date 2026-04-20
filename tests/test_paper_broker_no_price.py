"""Tests for paper broker entry_price handling on YES vs NO trades."""
from factory.broker import PaperBroker
from factory.db import FactoryDB
from factory.models import Signal


def _make_signal(outcome: str, market_price: float = 0.30) -> Signal:
    return Signal(
        strategy="test_strat",
        market_id="test-market:123",
        market_title="Test Market?",
        outcome=outcome,
        market_price=market_price,
        p_hat=0.5,
        ev_pp=20.0,
        confidence="medium",
        closes="2026-05-01",
        url="",
        rationale="test",
    )


def test_yes_entry_price_uses_market_price(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = PaperBroker(slippage=0.0, db=db)
    sig = _make_signal("YES", market_price=0.30)
    trade = broker.open_position(sig, 1.0)
    assert trade.entry_price == 0.30, f"YES entry should be market_price, got {trade.entry_price}"


def test_no_entry_price_uses_inverted_price(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = PaperBroker(slippage=0.0, db=db)
    sig = _make_signal("NO", market_price=0.30)
    trade = broker.open_position(sig, 1.0)
    # market_price=0.30 means YES=30%, NO=70%, so NO entry should be 0.70
    assert trade.entry_price == 0.70, f"NO entry should be 1-market_price=0.70, got {trade.entry_price}"


def test_no_shares_computed_correctly(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = PaperBroker(slippage=0.0, db=db)
    sig = _make_signal("NO", market_price=0.20)
    trade = broker.open_position(sig, 1.0)
    # NO price = 0.80, shares = 1.0 / 0.80 = 1.25
    assert trade.entry_price == 0.80
    assert abs(trade.shares - 1.25) < 0.01, f"Expected 1.25 shares, got {trade.shares}"


def test_yes_shares_computed_correctly(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = PaperBroker(slippage=0.0, db=db)
    sig = _make_signal("YES", market_price=0.25)
    trade = broker.open_position(sig, 1.0)
    # YES price = 0.25, shares = 1.0 / 0.25 = 4.0
    assert trade.entry_price == 0.25
    assert abs(trade.shares - 4.0) < 0.01, f"Expected 4.0 shares, got {trade.shares}"


def test_slippage_applied_after_direction(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = PaperBroker(slippage=0.01, db=db)
    sig = _make_signal("NO", market_price=0.30)
    trade = broker.open_position(sig, 1.0)
    # NO raw = 0.70, + slippage 0.01 = 0.71
    assert abs(trade.entry_price - 0.71) < 0.001, f"Expected 0.71, got {trade.entry_price}"

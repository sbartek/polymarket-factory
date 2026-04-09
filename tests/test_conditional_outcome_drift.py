"""Tests for conditional_outcome_drift strategy."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from factory.strategies.conditional_outcome_drift import ConditionalOutcomeDriftStrategy


def _event(slug: str, title: str, markets: list[dict], days: int = 5) -> dict:
    end_date = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "endDate": end_date,
        "volume24hr": 50_000,
        "markets": markets,
    }


def _market(mid: str, question: str, yes_price: float, volume: float = 5000.0) -> dict:
    return {
        "id": mid,
        "question": question,
        "closed": False,
        "volume": volume,
        "outcomePrices": [yes_price, 1 - yes_price],
    }


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get_recent_price_moves(self, min_move=0.08, max_hours=6.0):
        return self.rows


def test_scan_no_alert_when_db_unavailable():
    s = ConditionalOutcomeDriftStrategy()
    with patch("factory.strategies.conditional_outcome_drift.FactoryDB", side_effect=RuntimeError("no db")):
        assert s.scan([]) == []


def test_scan_emits_alert_for_child_drift_with_flat_parent():
    s = ConditionalOutcomeDriftStrategy()
    ev = _event("house", "House conditional seats", [
        _market("p", "Will Democrats win the House?", 0.42),
        _market("c", "If Democrats win the House, will they gain 10+ seats?", 0.62),
    ])
    rows = [
        {
            "market_id": "c",
            "market_slug": "child",
            "market_title": "If Democrats win the House, will they gain 10+ seats?",
            "cur_price": 0.62,
            "prev_price": 0.48,
            "price_move": 0.14,
            "volume": 9000,
            "volume_24hr": 20000,
        },
        {
            "market_id": "p",
            "market_slug": "parent",
            "market_title": "Will Democrats win the House?",
            "cur_price": 0.42,
            "prev_price": 0.41,
            "price_move": 0.01,
            "volume": 12000,
            "volume_24hr": 30000,
        },
    ]
    with patch("factory.strategies.conditional_outcome_drift.FactoryDB", return_value=_FakeDB(rows)):
        signals = s.scan([ev])
    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy == "conditional_outcome_drift"
    assert sig.outcome == "NO"
    assert sig.ev_pp > 0
    assert "child_move=" in sig.rationale


def test_scan_no_alert_when_parent_also_moves_large():
    s = ConditionalOutcomeDriftStrategy()
    ev = _event("house", "House conditional seats", [
        _market("p", "Will Democrats win the House?", 0.42),
        _market("c", "If Democrats win the House, will they gain 10+ seats?", 0.62),
    ])
    rows = [
        {
            "market_id": "c",
            "market_slug": "child",
            "market_title": "If Democrats win the House, will they gain 10+ seats?",
            "cur_price": 0.62,
            "prev_price": 0.48,
            "price_move": 0.14,
            "volume": 9000,
            "volume_24hr": 20000,
        },
        {
            "market_id": "p",
            "market_slug": "parent",
            "market_title": "Will Democrats win the House?",
            "cur_price": 0.42,
            "prev_price": 0.36,
            "price_move": 0.06,
            "volume": 12000,
            "volume_24hr": 30000,
        },
    ]
    with patch("factory.strategies.conditional_outcome_drift.FactoryDB", return_value=_FakeDB(rows)):
        assert s.scan([ev]) == []


def test_scan_no_alert_when_move_is_too_small():
    s = ConditionalOutcomeDriftStrategy()
    ev = _event("house", "House conditional seats", [
        _market("p", "Will Democrats win the House?", 0.42),
        _market("c", "If Democrats win the House, will they gain 10+ seats?", 0.55),
    ])
    rows = [
        {
            "market_id": "c",
            "market_slug": "child",
            "market_title": "If Democrats win the House, will they gain 10+ seats?",
            "cur_price": 0.55,
            "prev_price": 0.49,
            "price_move": 0.06,
            "volume": 9000,
            "volume_24hr": 20000,
        },
        {
            "market_id": "p",
            "market_slug": "parent",
            "market_title": "Will Democrats win the House?",
            "cur_price": 0.42,
            "prev_price": 0.41,
            "price_move": 0.01,
            "volume": 12000,
            "volume_24hr": 30000,
        },
    ]
    with patch("factory.strategies.conditional_outcome_drift.FactoryDB", return_value=_FakeDB(rows)):
        assert s.scan([ev]) == []


def test_strategy_is_alert_only():
    s = ConditionalOutcomeDriftStrategy()
    assert s.alert_only is True
    assert s.trading_enabled is False
    assert s.promotable is True

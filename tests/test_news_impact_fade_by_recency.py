"""Tests for news_impact_fade_by_recency strategy."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from factory.strategies.news_impact_fade_by_recency import (
    NewsImpactFadeByRecencyStrategy,
    _parse_news_time,
)


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get_recent_price_moves(self, min_move=0.08, max_hours=6.0):
        return self.rows


def _event(slug: str, title: str, yes_price: float = 0.62, days: int = 3) -> dict:
    end_date = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "endDate": end_date,
        "markets": [{
            "id": slug,
            "closed": False,
            "question": title,
            "outcomePrices": [yes_price, 1 - yes_price],
        }],
    }


def test_parse_news_time_handles_iso_z():
    dt = _parse_news_time("2026-04-10T10:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_scan_no_alert_when_db_unavailable():
    s = NewsImpactFadeByRecencyStrategy()
    with patch("factory.strategies.news_impact_fade_by_recency.FactoryDB", side_effect=RuntimeError("no db")):
        assert s.scan([]) == []


def test_scan_emits_alert_when_recent_news_supports_large_move():
    s = NewsImpactFadeByRecencyStrategy()
    now = datetime.now(UTC)
    rows = [{
        "market_id": "fed-market",
        "market_slug": "fed-market",
        "market_title": "Will the Fed cut rates by June?",
        "cur_price": 0.68,
        "prev_price": 0.50,
        "price_move": 0.18,
        "volume": 12000,
        "volume_24hr": 50000,
        "close_time": (now + timedelta(days=2)).isoformat(),
    }]
    news = [{"date": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"), "title": "Fed surprise statement"}]
    with patch("factory.strategies.news_impact_fade_by_recency.FactoryDB", return_value=_FakeDB(rows)), \
         patch.object(NewsImpactFadeByRecencyStrategy, "_fetch_news", return_value=news):
        signals = s.scan([_event("fed-market", "Will the Fed cut rates by June?", yes_price=0.68)])
    assert len(signals) == 1
    assert signals[0].strategy == "news_impact_fade_by_recency"
    assert signals[0].outcome == "NO"
    assert signals[0].ev_pp > 0


def test_scan_no_alert_without_recent_news():
    s = NewsImpactFadeByRecencyStrategy()
    now = datetime.now(UTC)
    rows = [{
        "market_id": "fed-market",
        "market_slug": "fed-market",
        "market_title": "Will the Fed cut rates by June?",
        "cur_price": 0.68,
        "prev_price": 0.50,
        "price_move": 0.18,
        "volume": 12000,
        "volume_24hr": 50000,
        "close_time": (now + timedelta(days=2)).isoformat(),
    }]
    stale_news = [{"date": (now - timedelta(hours=30)).isoformat().replace("+00:00", "Z"), "title": "Old Fed article"}]
    with patch("factory.strategies.news_impact_fade_by_recency.FactoryDB", return_value=_FakeDB(rows)), \
         patch.object(NewsImpactFadeByRecencyStrategy, "_fetch_news", return_value=stale_news):
        assert s.scan([_event("fed-market", "Will the Fed cut rates by June?", yes_price=0.68)]) == []


def test_scan_no_alert_for_small_move():
    s = NewsImpactFadeByRecencyStrategy()
    now = datetime.now(UTC)
    rows = [{
        "market_id": "fed-market",
        "market_slug": "fed-market",
        "market_title": "Will the Fed cut rates by June?",
        "cur_price": 0.56,
        "prev_price": 0.50,
        "price_move": 0.06,
        "volume": 12000,
        "volume_24hr": 50000,
        "close_time": (now + timedelta(days=2)).isoformat(),
    }]
    news = [{"date": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"), "title": "Fed surprise statement"}]
    with patch("factory.strategies.news_impact_fade_by_recency.FactoryDB", return_value=_FakeDB(rows)), \
         patch.object(NewsImpactFadeByRecencyStrategy, "_fetch_news", return_value=news):
        assert s.scan([_event("fed-market", "Will the Fed cut rates by June?", yes_price=0.56)]) == []


def test_strategy_is_alert_only():
    s = NewsImpactFadeByRecencyStrategy()
    assert s.alert_only is True
    assert s.trading_enabled is False
    assert s.promotable is True

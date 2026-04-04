"""Tests for resolution_hunter_v2 — political-only, no sports."""
from unittest.mock import patch

from factory.strategies.resolution_hunter_v2 import (
    ResolutionHunterV2Strategy,
    _is_political,
    _is_excluded,
)


class TestFilters:
    def test_political_keywords_match(self):
        assert _is_political("Will Trump sign the tariff bill?")
        assert _is_political("Federal Reserve rate cut in April")
        assert _is_political("Iran ceasefire by end of month")

    def test_non_political_no_match(self):
        assert not _is_political("Temperature in NYC tomorrow")
        assert not _is_political("Bitcoin above $100k")

    def test_excluded_sports(self):
        assert _is_excluded("Lakers vs. Thunder")
        assert _is_excluded("NBA MVP award")
        assert _is_excluded("IPL Royal Challengers")

    def test_excluded_weather(self):
        assert _is_excluded("Highest temperature in Seoul 14°C")

    def test_excluded_price(self):
        assert _is_excluded("Bitcoin price above $100k")

    def test_political_not_excluded(self):
        assert not _is_excluded("Will Trump sign the tariff bill?")


class TestStrategy:
    def test_is_alert_only(self):
        s = ResolutionHunterV2Strategy()
        assert s.alert_only is True
        assert s.promotable is True
        assert s.min_ev_pp == 20.0

    def test_skips_sports_events(self):
        s = ResolutionHunterV2Strategy()
        events = [{
            "slug": "nba-lakers-thunder",
            "title": "Lakers vs. Thunder",
            "volume24hr": 100_000,
            "endDate": "2026-04-15",
            "markets": [{"id": "m1", "outcomePrices": '[0.40,0.60]', "closed": False}],
        }]
        signals = s.scan(events)
        assert len(signals) == 0

    def test_skips_weather_events(self):
        s = ResolutionHunterV2Strategy()
        events = [{
            "slug": "temp-nyc",
            "title": "Highest temperature in NYC 60°F",
            "volume24hr": 100_000,
            "endDate": "2026-04-15",
            "markets": [{"id": "m1", "outcomePrices": '[0.40,0.60]', "closed": False}],
        }]
        signals = s.scan(events)
        assert len(signals) == 0

    @patch("factory.strategies.resolution_hunter_v2._fetch_news", return_value=[
        {"title": "Trump signs tariff bill", "date": "2026-04-03", "body": "The bill was signed today."},
        {"title": "Tariff confirmed", "date": "2026-04-03", "body": "Markets react to the news."},
    ])
    @patch("factory.strategies.resolution_hunter_v2.call_claude", return_value='[{"slug": "trump-tariff", "outcome": "YES", "confidence": 95, "reason": "Bill was signed"}]')
    def test_signals_on_political_event(self, mock_claude, mock_news):
        s = ResolutionHunterV2Strategy()
        events = [{
            "slug": "trump-tariff",
            "title": "Will Trump sign the tariff bill by April 10?",
            "volume24hr": 200_000,
            "endDate": "2026-04-15",
            "markets": [{"id": "m1", "outcomePrices": '[0.40,0.60]', "closed": False}],
        }]
        signals = s.scan(events)
        assert len(signals) == 1
        assert signals[0].outcome == "YES"
        assert signals[0].confidence == "high"

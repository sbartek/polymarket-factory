"""Tests for weather_edge_v2 — NO-only, fixed range boundary."""
from unittest.mock import patch

from factory.strategies.weather_edge_v2 import (
    WeatherEdgeV2Strategy,
    _prob_from_values,
    _parse_submarket_question,
)


class TestProbFromValues:
    def test_range_exclusive_upper_bound(self):
        """v2 fix: 'between 60-61°F' means [60, 61) — value exactly at 61 should NOT count."""
        values = [59.0, 60.0, 60.5, 61.0, 62.0]
        parsed = {"direction": "range", "threshold_low": 60, "threshold_high": 61}
        prob = _prob_from_values(values, parsed)
        # 60.0 and 60.5 match [60, 61), but 61.0 does NOT
        assert prob == 2 / 5

    def test_range_v1_would_have_included_upper(self):
        """Verify the fix: v1 used <= which would count 61.0 as in-range."""
        values = [60.0, 60.5, 61.0]
        parsed = {"direction": "range", "threshold_low": 60, "threshold_high": 61}
        prob = _prob_from_values(values, parsed)
        # v2: 60.0 and 60.5 match, 61.0 does NOT → 2/3
        assert prob == round(2 / 3, 4)

    def test_above_threshold(self):
        values = [58.0, 60.0, 62.0]
        parsed = {"direction": "above", "threshold": 60}
        assert _prob_from_values(values, parsed) == round(2 / 3, 4)

    def test_below_threshold(self):
        values = [58.0, 60.0, 62.0]
        parsed = {"direction": "below", "threshold": 60}
        assert _prob_from_values(values, parsed) == round(2 / 3, 4)


class TestParseQuestion:
    def test_parses_range_question(self):
        result = _parse_submarket_question(
            "Will the highest temperature in Seoul be between 14-15°C on April 5?"
        )
        assert result is not None
        assert result["location"] == "Seoul"
        assert result["metric"] == "temperature_max"
        assert result["unit"] == "C"
        assert result["direction"] == "range"
        assert result["threshold_low"] == 14
        assert result["threshold_high"] == 15

    def test_parses_above_question(self):
        result = _parse_submarket_question(
            "Will the highest temperature in Dallas be 84°F or above on April 1?"
        )
        assert result is not None
        assert result["direction"] == "above"
        assert result["threshold"] == 84

    def test_returns_none_for_non_weather(self):
        assert _parse_submarket_question("Will Trump win the election?") is None


class TestStrategy:
    def test_is_alert_only(self):
        s = WeatherEdgeV2Strategy()
        assert s.alert_only is True
        assert s.promotable is True
        assert s.min_ev_pp == 18.0

    def test_only_no_signals(self):
        """v2 should NEVER produce YES signals."""
        s = WeatherEdgeV2Strategy()

        # Mock a weather event where ensemble says 2% but market says 30%
        events = [{
            "slug": "temp-seoul",
            "title": "Highest temperature in Seoul",
            "endDate": "2026-04-07",
            "markets": [{
                "id": "m1",
                "question": "Will the highest temperature in Seoul be 14°C on April 5?",
                "outcomePrices": '[0.30,0.70]',
                "closed": False,
            }],
        }]

        # 50 ensemble members, only 1 hits the 14°C bin
        fake_values = [12.0] * 49 + [14.5]

        with patch.object(s, "_get_values", return_value=fake_values):
            signals = s.scan(events)

        # Should only produce NO signals
        for sig in signals:
            assert sig.outcome == "NO"

    @patch("factory.strategies.weather_edge_v2.fetch_by_tag", return_value=[])
    def test_skips_when_ensemble_agrees_with_market(self, _mock_tag):
        """If ensemble says bin is likely (>5%), no signal."""
        s = WeatherEdgeV2Strategy()

        events = [{
            "slug": "temp-nyc",
            "title": "Highest temperature in NYC",
            "endDate": "2026-04-07",
            "markets": [{
                "id": "m1",
                "question": "Will the highest temperature in NYC be between 60-61°F on April 5?",
                "outcomePrices": '[0.20,0.80]',
                "closed": False,
            }],
        }]

        # 10 of 50 ensemble members hit the bin — 20% probability, above MAX_ENSEMBLE_PROB
        fake_values = [60.5] * 10 + [55.0] * 40

        with patch.object(s, "_get_values", return_value=fake_values):
            signals = s.scan(events)

        assert len(signals) == 0

    @patch("factory.strategies.weather_edge_v2.fetch_by_tag", return_value=[])
    def test_skips_low_market_price(self, _mock_tag):
        """If market already prices the bin low (<15%), no edge to capture."""
        s = WeatherEdgeV2Strategy()

        events = [{
            "slug": "temp-paris",
            "title": "Highest temperature in Paris",
            "endDate": "2026-04-07",
            "markets": [{
                "id": "m1",
                "question": "Will the highest temperature in Paris be 13°C on April 5?",
                "outcomePrices": '[0.05,0.95]',  # already priced low
                "closed": False,
            }],
        }]

        with patch.object(s, "_get_values", return_value=[10.0] * 50):
            signals = s.scan(events)

        assert len(signals) == 0

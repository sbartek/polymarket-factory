"""Tests for weather_edge_v2 — widened-bin probability model and NO-only behavior."""
from unittest.mock import patch

from factory.strategies.weather_edge_v2 import (
    ENSEMBLE_WIDEN_C,
    MIN_ENSEMBLE_FLOOR,
    WeatherEdgeV2Strategy,
    _prob_from_values,
    _parse_submarket_question,
)


class TestProbFromValues:
    def test_range_uses_widened_bin_logic(self):
        """v2 intentionally widens the effective range to offset ensemble under-dispersion."""
        values = [58.4, 58.5, 59.5, 60.9, 61.4, 62.6]
        parsed = {"direction": "range", "threshold_low": 60, "threshold_high": 61}
        prob = _prob_from_values(values, parsed)
        # With ENSEMBLE_WIDEN_C=1.5 the effective interval is [58.5, 62.5),
        # so 58.5, 59.5, 60.9 and 61.4 count => 4 / 6.
        assert prob == round(4 / 6, 4)

    def test_range_probability_never_drops_below_floor(self):
        """Even zero raw hits should return the configured probability floor."""
        values = [10.0, 20.0, 30.0]
        parsed = {"direction": "range", "threshold_low": 60, "threshold_high": 61}
        prob = _prob_from_values(values, parsed)
        assert prob == MIN_ENSEMBLE_FLOOR

    def test_above_threshold_uses_widening_and_floor(self):
        values = [58.0, 60.0, 62.0]
        parsed = {"direction": "above", "threshold": 60}
        # threshold is relaxed by ENSEMBLE_WIDEN_C on the low side
        expected = round(2 / 3, 4)
        assert _prob_from_values(values, parsed) == max(expected, MIN_ENSEMBLE_FLOOR)

    def test_below_threshold_uses_widening_and_floor(self):
        values = [58.0, 60.0, 62.0]
        parsed = {"direction": "below", "threshold": 60}
        # threshold is relaxed by ENSEMBLE_WIDEN_C on the high side
        expected = round(2 / 3, 4)
        assert _prob_from_values(values, parsed) == max(expected, MIN_ENSEMBLE_FLOOR)


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
    def test_strategy_flags_match_current_v2_design(self):
        s = WeatherEdgeV2Strategy()
        assert s.alert_only is True
        assert s.promotable is False
        assert s.min_ev_pp == 18.0

    def test_only_no_signals(self):
        """v2 should NEVER produce YES signals."""
        s = WeatherEdgeV2Strategy()

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

        fake_values = [12.0] * 49 + [14.5]

        with patch.object(s, "_get_values", return_value=fake_values):
            signals = s.scan(events)

        for sig in signals:
            assert sig.outcome == "NO"

    @patch("factory.strategies.weather_edge_v2.fetch_by_tag", return_value=[])
    def test_skips_when_adjusted_ensemble_probability_is_too_high(self, _mock_tag):
        """If the widened/floored ensemble probability exceeds the max threshold, no signal."""
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
                "outcomePrices": '[0.05,0.95]',
                "closed": False,
            }],
        }]

        with patch.object(s, "_get_values", return_value=[10.0] * 50):
            signals = s.scan(events)

        assert len(signals) == 0

    @patch("factory.strategies.weather_edge_v2.fetch_by_tag", return_value=[])
    def test_floor_can_block_signal_even_when_raw_probability_is_zero(self, _mock_tag):
        """The probability floor is part of the v2 contract and should suppress marginal NO edges."""
        s = WeatherEdgeV2Strategy()

        events = [{
            "slug": "temp-rome",
            "title": "Highest temperature in Rome",
            "endDate": "2026-04-07",
            "markets": [{
                "id": "m1",
                "question": "Will the highest temperature in Rome be 13°C on April 5?",
                "outcomePrices": '[0.25,0.75]',
                "closed": False,
            }],
        }]

        # Raw ensemble probability would be 0, but the floor lifts it to 10%,
        # so the NO edge is only 15pp and should stay below min_ev_pp=18.
        with patch.object(s, "_get_values", return_value=[30.0] * 50):
            signals = s.scan(events)

        assert len(signals) == 0

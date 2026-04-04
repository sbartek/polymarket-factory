"""Tests for fade_certainty_v2 — binary-only, sub-market level."""
from factory.strategies.fade_certainty_v2 import FadeCertaintyV2Strategy


def _binary_event(slug="test-event", yes_price=0.97, volume=100_000, end_date="2026-05-15", title="Will X happen?", market_id="m1"):
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "endDate": end_date,
        "markets": [
            {"id": market_id, "outcomePrices": f'[{yes_price},{1-yes_price}]', "closed": False}
        ],
    }


def _multi_outcome_event(slug="multi-event"):
    return {
        "slug": slug,
        "title": "Who will win?",
        "volume24hr": 200_000,
        "endDate": "2026-06-01",
        "markets": [
            {"id": "m1", "outcomePrices": '[0.40,0.60]', "closed": False},
            {"id": "m2", "outcomePrices": '[0.60,0.40]', "closed": False},
        ],
    }


class TestFadeCertaintyV2:
    def test_strategy_is_alert_only(self):
        s = FadeCertaintyV2Strategy()
        assert s.alert_only is True
        assert s.promotable is True

    def test_signals_on_high_extreme_binary(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(yes_price=0.97)])
        assert len(signals) == 1
        assert signals[0].outcome == "NO"
        assert signals[0].market_id == "test-event:m1"

    def test_signals_on_low_extreme_binary(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(yes_price=0.03)])
        assert len(signals) == 1
        assert signals[0].outcome == "YES"

    def test_skips_mid_range_price(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(yes_price=0.60)])
        assert len(signals) == 0

    def test_skips_multi_outcome_events(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_multi_outcome_event()])
        assert len(signals) == 0

    def test_skips_sports(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(title="Lakers vs. Thunder", yes_price=0.97)])
        assert len(signals) == 0

    def test_skips_elections(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(title="Election Winner 2026", yes_price=0.97)])
        assert len(signals) == 0

    def test_skips_low_volume(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(volume=1000)])
        assert len(signals) == 0

    def test_skips_too_close(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(end_date="2026-04-05")])  # within 7 days
        assert len(signals) == 0

    def test_market_id_includes_sub_market(self):
        s = FadeCertaintyV2Strategy()
        signals = s.scan([_binary_event(slug="my-event", market_id="12345", yes_price=0.97)])
        assert signals[0].market_id == "my-event:12345"

    def test_populates_check_details(self):
        s = FadeCertaintyV2Strategy()
        s.scan([_binary_event(yes_price=0.97)])
        assert len(s.last_check_details) == 1
        assert s.last_check_details[0]["decision"] == "alert"

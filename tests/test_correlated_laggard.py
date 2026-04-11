from datetime import datetime, timedelta, UTC

from factory.runner import format_wa_summary
from factory.strategies.correlated_laggard import CorrelatedLaggardStrategy

_FUTURE_DATE = (datetime.now(UTC) + timedelta(days=14)).strftime("%Y-%m-%dT12:00:00Z")


def _market(slug: str, title: str, price: float, volume: float) -> dict:
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "endDate": _FUTURE_DATE,
        "markets": [{
            "closed": False,
            "outcomePrices": [price, 1 - price],
        }],
    }


def test_scan_emits_alert_for_liquid_leader_and_laggard_gap():
    strategy = CorrelatedLaggardStrategy()
    markets = [
        _market("leader", "Will Trump tariff pause happen by May?", 0.74, 80000),
        _market("laggard", "Will Trump tariff pause extend into June?", 0.46, 25000),
        _market("other", "Will the Fed cut rates by June?", 0.52, 90000),
    ]

    signals = strategy.scan(markets)

    assert len(signals) == 1
    assert signals[0].strategy == "correlated_laggard"
    assert signals[0].market_id == "laggard"
    assert signals[0].outcome == "YES"
    assert signals[0].ev_pp == 28.0
    assert strategy.last_check_details[0]["decision"] == "alert"


def test_scan_can_emit_no_alert_when_laggard_is_richer_than_leader():
    strategy = CorrelatedLaggardStrategy()
    markets = [
        _market("leader", "Will Trump tariff pause happen by May?", 0.32, 90000),
        _market("laggard", "Will Trump tariff pause extend into June?", 0.59, 20000),
    ]

    signals = strategy.scan(markets)

    assert len(signals) == 1
    assert signals[0].outcome == "NO"
    assert signals[0].market_price == 0.41
    assert signals[0].p_hat == 0.68


def test_rejects_unrelated_weather_markets():
    strategy = CorrelatedLaggardStrategy()
    markets = [
        _market("shanghai", "Highest temperature in Shanghai on April 12?", 0.45, 50000),
        _market("seattle", "Highest temperature in Seattle on April 11?", 0.72, 80000),
    ]
    signals = strategy.scan(markets)
    assert len(signals) == 0


def test_rejects_unrelated_sports_markets():
    strategy = CorrelatedLaggardStrategy()
    markets = [
        _market("dota", "Dota 2: GLYPH vs PlayTime (BO3) - DreamLeague", 0.45, 30000),
        _market("cs2", "CS2: Ruby vs Stax (BO3) - PGL Major", 0.72, 60000),
    ]
    signals = strategy.scan(markets)
    assert len(signals) == 0


def test_format_wa_summary_includes_alerts():
    strategy = CorrelatedLaggardStrategy()
    signal = strategy.scan([
        _market("leader", "Will Trump tariff pause happen by May?", 0.73, 90000),
        _market("laggard", "Will Trump tariff pause extend into June?", 0.45, 22000),
    ])[0]
    stats = {
        "by_strategy": {},
        "by_status_group": {},
        "total_pnl": 0.0,
        "total_staked": 0.0,
        "roi": 0.0,
        "open": 0,
    }

    text = format_wa_summary([], [signal], 0, stats, "2026-03-31 19:30", [])

    assert "Alerts:" in text
    assert "correlated_laggard" in text

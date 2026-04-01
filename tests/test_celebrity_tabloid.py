from datetime import UTC, datetime, timedelta

from factory.runner import format_wa_summary
from factory.strategies.celebrity_tabloid import CelebrityTabloidStrategy


def _market(
    slug: str,
    title: str,
    price: float,
    volume: float,
    tags: list[dict] | None = None,
    end_date: str | None = None,
) -> dict:
    if end_date is None:
        end_date = (datetime.now(UTC) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "endDate": end_date,
        "category": "Entertainment",
        "tags": tags or [{"slug": "celebrity", "label": "Celebrity"}],
        "markets": [{
            "closed": False,
            "outcomePrices": [price, 1 - price],
        }],
    }


def test_scan_emits_alert_for_corroborated_celebrity_event(monkeypatch):
    strategy = CelebrityTabloidStrategy()

    monkeypatch.setattr(
        strategy,
        "_fetch_gossip_hits",
        lambda candidate, n=6: [
            {
                "title": "People says Taylor Swift and Travis Kelce engagement rumors are heating up",
                "body": "Taylor Swift and Travis Kelce are reportedly getting engaged soon.",
                "href": "https://people.com/taylor-swift-travis-kelce-engagement-rumors-123",
            },
            {
                "title": "TMZ: Taylor Swift and Travis Kelce eye wedding plans",
                "body": "Sources say the couple is together and discussing marriage.",
                "href": "https://tmz.com/2026/04/01/taylor-swift-travis-kelce-wedding",
            },
        ],
    )

    signals = strategy.scan([
        _market("swift-kelce-engaged", "Will Taylor Swift and Travis Kelce get engaged in 2026?", 0.41, 28000),
    ])

    assert len(signals) == 1
    signal = signals[0]
    assert signal.strategy == "celebrity_tabloid"
    assert signal.market_id == "swift-kelce-engaged"
    assert signal.outcome == "YES"
    assert signal.ev_pp >= strategy.min_ev_pp
    assert "tabloid_romance_up" in signal.rationale
    assert strategy.last_check_details[0]["decision"] == "alert"


def test_scan_fails_closed_when_gossip_is_sparse_or_contradictory(monkeypatch):
    strategy = CelebrityTabloidStrategy()

    monkeypatch.setattr(
        strategy,
        "_fetch_gossip_hits",
        lambda candidate, n=6: [
            {
                "title": "Page Six says Taylor Swift and Travis Kelce are not dating rumor debunked",
                "body": "The outlet says the engagement rumor is false and the pair may have split.",
                "href": "https://pagesix.com/2026/04/01/taylor-swift-travis-kelce-rumor-debunked",
            },
        ],
    )

    signals = strategy.scan([
        _market("swift-kelce-engaged", "Will Taylor Swift and Travis Kelce get engaged in 2026?", 0.41, 28000),
    ])

    assert signals == []
    assert strategy.last_check_details[0]["decision"] == "watch"
    assert strategy.last_check_details[0]["reason"] in {
        "insufficient_gossip_corroboration",
        "contradictory_gossip_coverage",
    }


def test_format_wa_summary_includes_celebrity_tabloid_alert(monkeypatch):
    strategy = CelebrityTabloidStrategy()
    monkeypatch.setattr(
        strategy,
        "_fetch_gossip_hits",
        lambda candidate, n=6: [
            {
                "title": "People reports Rihanna is expecting a baby",
                "body": "Rihanna is pregnant again according to multiple sources.",
                "href": "https://people.com/rihanna-pregnant-again-123",
            },
            {
                "title": "Us Weekly: Rihanna baby news sparks buzz",
                "body": "The singer is reportedly expecting.",
                "href": "https://usmagazine.com/celebrity-moms/news/rihanna-expecting",
            },
        ],
    )
    signal = strategy.scan([
        _market("rihanna-pregnant", "Will Rihanna announce she is pregnant this month?", 0.36, 22000),
    ])[0]
    stats = {
        "by_strategy": {},
        "by_status_group": {},
        "total_pnl": 0.0,
        "total_staked": 0.0,
        "roi": 0.0,
        "open": 0,
    }

    text = format_wa_summary([], [signal], 0, stats, "2026-04-01 19:30", [])

    assert "Alerts:" in text
    assert "celebrity_tabloid" in text

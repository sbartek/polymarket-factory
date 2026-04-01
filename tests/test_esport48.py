from datetime import UTC, datetime, timedelta

from factory.runner import format_wa_summary
from factory.strategies.esport48 import Esport48Strategy


def _market(
    slug: str,
    title: str,
    price: float,
    volume: float,
    liquidity: float,
    end_date: str | None = None,
    tags: list[dict] | None = None,
) -> dict:
    if end_date is None:
        end_date = (datetime.now(UTC) + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "liquidity": liquidity,
        "endDate": end_date,
        "tags": tags or [{"slug": "esports", "label": "Esports"}],
        "markets": [{
            "closed": False,
            "outcomePrices": [price, 1 - price],
        }],
    }


def test_scan_emits_alert_for_liquid_esport_market_inside_48h():
    strategy = Esport48Strategy()
    signals = strategy.scan([
        _market("valorant-final", "Valorant Champions Final winner", 0.79, 28000, 9000),
        _market("macro", "Will CPI rise in May?", 0.61, 50000, 12000, tags=[{"slug": "macro"}]),
    ])

    assert len(signals) == 1
    signal = signals[0]
    assert signal.strategy == "esport48"
    assert signal.market_id == "valorant-final"
    assert signal.outcome == "NO"
    assert signal.ev_pp >= strategy.min_ev_pp
    assert "overreaction/underreaction_edge" in signal.rationale
    assert strategy.last_check_details[0]["decision"] == "alert"


def test_scan_skips_dead_or_non_esport_books():
    strategy = Esport48Strategy()
    signals = strategy.scan([
        _market("thin", "CS2 semifinal winner", 0.75, 3000, 800),
        _market(
            "long-dated",
            "League of Legends finals winner",
            0.76,
            20000,
            9000,
            end_date=(datetime.now(UTC) + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        ),
        _market("sports", "Will Barcelona win El Clasico?", 0.73, 24000, 9000, tags=[{"slug": "soccer", "label": "Soccer"}]),
    ])

    assert signals == []
    assert strategy.last_check_details == []


def test_format_wa_summary_includes_esport48_alerts():
    strategy = Esport48Strategy()
    signal = strategy.scan([
        _market("cs2-major", "CS2 Major grand final winner", 0.78, 25000, 7000),
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
    assert "esport48" in text

"""
Tests for polling_vs_market strategy:
- _is_pollable() keyword matching
- scan() candidate filtering (volume, days, price)
- scan() skips market when no polling data returned
- scan() emits signal when LLM returns a valid gap
- scan() respects MAX_TRADES_PER_RUN cap
- last_check_details populated correctly
"""
from datetime import UTC, datetime, timedelta

import pytest

from factory.strategies.polling_vs_market import (
    MIN_GAP_PP,
    PollingVsMarketStrategy,
)


def _market(
    slug: str,
    title: str,
    price: float = 0.5,
    volume: float = 50_000,
    days: int = 30,
) -> dict:
    end_date = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "endDate": end_date,
        "markets": [{"closed": False, "outcomePrices": [str(price), str(1 - price)]}],
    }


# ---------------------------------------------------------------------------
# _is_pollable
# ---------------------------------------------------------------------------

def test_is_pollable_matches_election_keyword():
    s = PollingVsMarketStrategy()
    assert s._is_pollable("Will Trump win the 2026 election?")


def test_is_pollable_matches_approval_keyword():
    s = PollingVsMarketStrategy()
    assert s._is_pollable("Will Biden's approval rating exceed 45%?")


def test_is_pollable_rejects_crypto_title():
    s = PollingVsMarketStrategy()
    assert not s._is_pollable("Will Bitcoin hit $100k by June?")


def test_is_pollable_case_insensitive():
    s = PollingVsMarketStrategy()
    assert s._is_pollable("TRUMP APPROVAL RATING ABOVE 50%?")


# ---------------------------------------------------------------------------
# scan() candidate filtering
# ---------------------------------------------------------------------------

def test_scan_skips_low_volume_market(monkeypatch):
    s = PollingVsMarketStrategy()
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: [])
    signals = s.scan([_market("low-vol", "Trump approval above 50%?", volume=100)])
    assert signals == []
    assert s.last_check_details == []


def test_scan_skips_market_closing_too_soon(monkeypatch):
    s = PollingVsMarketStrategy()
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: [])
    signals = s.scan([_market("soon", "Trump approval above 50%?", days=1)])
    assert signals == []


def test_scan_skips_market_too_far_out(monkeypatch):
    s = PollingVsMarketStrategy()
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: [])
    signals = s.scan([_market("far", "Trump approval above 50%?", days=365)])
    assert signals == []


def test_scan_skips_market_price_too_extreme(monkeypatch):
    s = PollingVsMarketStrategy()
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: [])
    signals = s.scan([_market("extreme", "Trump approval above 50%?", price=0.02)])
    assert signals == []


# ---------------------------------------------------------------------------
# scan() with LLM responses
# ---------------------------------------------------------------------------

def test_scan_skips_when_no_polling_data(monkeypatch):
    s = PollingVsMarketStrategy()
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: [])
    signals = s.scan([_market("trump-approval", "Trump approval above 50%?")])
    assert signals == []
    assert s.last_check_details[0]["decision"] == "skipped"
    assert s.last_check_details[0]["reason"] == "no_polling_data_or_gap_too_small"


def test_scan_emits_signal_when_gap_exceeds_threshold(monkeypatch):
    fake_news = [{"date": "2026-04-01", "title": "Trump approval at 38%", "body": "Poll shows 38% approval.", "source": "FiveThirtyEight"}]
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: fake_news)

    llm_response = (
        '<signal>{"outcome": "NO", "market_price_pct": 60, "polling_p_hat_pct": 38, '
        '"ev_pp": 22, "confidence": "high", "poll_source": "FiveThirtyEight", '
        '"rationale": "Poll shows 38% vs 60% market price"}</signal>'
    )
    monkeypatch.setattr("factory.strategies.polling_vs_market.call_claude", lambda prompt, max_tokens=600: llm_response)

    s = PollingVsMarketStrategy()
    signals = s.scan([_market("trump-approval", "Trump approval above 50%?")])

    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy == "polling_vs_market"
    assert sig.outcome == "NO"
    assert sig.ev_pp == 22.0
    assert sig.confidence == "high"
    assert "FiveThirtyEight" in sig.rationale
    assert s.last_check_details[0]["decision"] == "signal"


def test_scan_skips_when_gap_below_threshold(monkeypatch):
    fake_news = [{"date": "2026-04-01", "title": "Trump approval at 55%", "body": "Poll shows 55%.", "source": "Gallup"}]
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: fake_news)

    gap = MIN_GAP_PP - 1
    llm_response = (
        f'<signal>{{"outcome": "YES", "market_price_pct": 50, "polling_p_hat_pct": 55, '
        f'"ev_pp": {gap}, "confidence": "low", "poll_source": "Gallup", '
        f'"rationale": "Small gap only"}}</signal>'
    )
    monkeypatch.setattr("factory.strategies.polling_vs_market.call_claude", lambda prompt, max_tokens=600: llm_response)

    s = PollingVsMarketStrategy()
    signals = s.scan([_market("senate-control", "Republicans win Senate in 2026?")])
    assert signals == []


def test_scan_handles_malformed_llm_response(monkeypatch):
    fake_news = [{"date": "2026-04-01", "title": "Some poll", "body": "Numbers here.", "source": "X"}]
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: fake_news)
    monkeypatch.setattr("factory.strategies.polling_vs_market.call_claude", lambda prompt, max_tokens=600: "no signal tags here")

    s = PollingVsMarketStrategy()
    signals = s.scan([_market("trump-approval", "Trump approval above 50%?")])
    assert signals == []


def test_scan_respects_max_trades_per_run(monkeypatch):
    fake_news = [{"date": "2026-04-01", "title": "Poll result", "body": "Big gap.", "source": "538"}]
    monkeypatch.setattr("factory.strategies.polling_vs_market._fetch_news", lambda q, n=5: fake_news)

    llm_response = (
        '<signal>{"outcome": "NO", "market_price_pct": 65, "polling_p_hat_pct": 38, '
        '"ev_pp": 27, "confidence": "high", "poll_source": "538", '
        '"rationale": "Gap found"}</signal>'
    )
    monkeypatch.setattr("factory.strategies.polling_vs_market.call_claude", lambda prompt, max_tokens=600: llm_response)

    markets = [
        _market(f"election-{i}", f"Will candidate {i} win the election?")
        for i in range(5)
    ]
    s = PollingVsMarketStrategy()
    signals = s.scan(markets)
    assert len(signals) == 2  # MAX_TRADES_PER_RUN = 2

"""
Tests for mutually_exclusive_oversum strategy.
"""
from datetime import UTC, datetime, timedelta

from factory.strategies.mutually_exclusive_oversum import (
    MIN_OVERSUM,
    MutuallyExclusiveOversumStrategy,
    _is_incomplete_field,
)


def _market(slug: str, title: str, legs: list[tuple[str, float]], days: int = 20) -> dict:
    """Build a fake multi-outcome event."""
    end_date = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    markets = []
    for i, (question, yes_price) in enumerate(legs):
        markets.append({
            "id": str(1000 + i),
            "closed": False,
            "question": question,
            "outcomePrices": [yes_price, 1 - yes_price],
            "volume": 5000.0,
        })
    return {
        "slug": slug,
        "title": title,
        "endDate": end_date,
        "markets": markets,
    }


# ---------------------------------------------------------------------------
# _is_incomplete_field
# ---------------------------------------------------------------------------

def test_incomplete_field_winner_no_catchall():
    legs = [{"question": "Team A"}, {"question": "Team B"}, {"question": "Team C"}]
    assert _is_incomplete_field("2026 NBA Champion winner", legs)


def test_incomplete_field_with_catchall_not_incomplete():
    legs = [{"question": "Team A"}, {"question": "Team B"}, {"question": "Field"}]
    assert not _is_incomplete_field("2026 NBA Champion winner", legs)


def test_incomplete_field_non_open_title_not_incomplete():
    legs = [{"question": "0-2"}, {"question": "3-5"}, {"question": "6+"}]
    assert not _is_incomplete_field("How many countries will strike in 2026?", legs)


# ---------------------------------------------------------------------------
# scan() filtering
# ---------------------------------------------------------------------------

def test_scan_no_signal_when_undersum():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("some-event", "Some count market", [
        ("0", 0.20), ("1", 0.25), ("2", 0.30),
    ])
    signals = s.scan([ev])
    assert signals == []


def test_scan_no_signal_below_min_legs():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("binary-event", "Binary market", [
        ("Yes", 0.65), ("No", 0.50),   # sum=1.15 but only 2 legs
    ])
    signals = s.scan([ev])
    assert signals == []


def test_scan_no_signal_closing_too_soon():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("imminent", "Count market", [
        ("0", 0.40), ("1", 0.40), ("2", 0.40),
    ], days=2)
    signals = s.scan([ev])
    assert signals == []


def test_scan_no_signal_incomplete_open_field():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("nba-winner", "2026 NBA Champion winner", [
        ("Celtics", 0.40), ("Lakers", 0.40), ("Warriors", 0.40),
    ])
    signals = s.scan([ev])
    assert signals == []


# ---------------------------------------------------------------------------
# scan() signal generation
# ---------------------------------------------------------------------------

def test_scan_emits_alert_on_oversum():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("count-event", "How many strikes in 2026?", [
        ("0", 0.30), ("1", 0.40), ("2", 0.35), ("3+", 0.25),
    ])
    # sum = 1.30 → oversum
    signals = s.scan([ev])
    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy == "mutually_exclusive_oversum"
    assert sig.outcome == "NO"
    assert sig.ev_pp > 0


def test_scan_picks_highest_yes_price_as_chosen():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("oversum-event", "Who leads in Q3?", [
        ("Alice", 0.25), ("Bob", 0.50), ("Carol", 0.40),
    ])
    # sum = 1.15, Bob is most overpriced
    signals = s.scan([ev])
    assert len(signals) == 1
    # market_id should include Bob's sub-market (id=1001, the second leg)
    assert "1001" in signals[0].market_id


def test_scan_signal_is_no_outcome():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("oversum-event", "Who leads?", [
        ("A", 0.30), ("B", 0.45), ("C", 0.40),
    ])
    signals = s.scan([ev])
    assert signals[0].outcome == "NO"


def test_scan_populates_last_check_details():
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("oversum-event", "Who leads?", [
        ("A", 0.30), ("B", 0.45), ("C", 0.40),
    ])
    s.scan([ev])
    assert len(s.last_check_details) == 1
    d = s.last_check_details[0]
    assert d["decision"] == "alert"
    assert d["oversum_pp"] > 0
    assert d["leg_count"] == 3


def test_scan_respects_max_alerts_per_run():
    s = MutuallyExclusiveOversumStrategy()
    markets = [
        _market(f"event-{i}", f"Count market {i}", [
            ("0", 0.40), ("1", 0.40), ("2", 0.40),
        ])
        for i in range(6)
    ]
    signals = s.scan(markets)
    assert len(signals) <= 3  # MAX_ALERTS_PER_RUN


def test_scan_rejects_price_target_legs():
    """'Will BTC hit $80k?' — multiple legs can resolve YES, not mutually exclusive."""
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("btc-price", "What price will BTC hit in April?", [
        ("Will BTC hit $70k?", 0.50),
        ("Will BTC hit $80k?", 0.45),
        ("Will BTC hit $90k?", 0.40),
    ])
    signals = s.scan([ev])
    assert signals == []


def test_scan_rejects_extreme_oversum():
    """Sum > 1.50 almost certainly means non-exclusive legs."""
    s = MutuallyExclusiveOversumStrategy()
    ev = _market("extreme", "Some market", [
        ("A", 0.55), ("B", 0.55), ("C", 0.55),
    ])
    signals = s.scan([ev])
    assert signals == []


def test_strategy_is_paper_trading():
    s = MutuallyExclusiveOversumStrategy()
    assert s.alert_only is False
    assert s.trading_enabled is True
    assert s.promotable is True

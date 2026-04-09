"""Tests for conditional_outcome_count_asymmetry strategy."""
from datetime import UTC, datetime, timedelta

from factory.strategies.conditional_outcome_count_asymmetry import (
    ConditionalOutcomeCountAsymmetryStrategy,
    _looks_like_count_bucket,
    _parse_conditional_question,
)


def _event(slug: str, title: str, markets: list[dict], days: int = 7) -> dict:
    end_date = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "endDate": end_date,
        "volume24hr": 50_000,
        "markets": markets,
    }


def _market(mid: str, question: str, yes_price: float, volume: float = 5000.0) -> dict:
    return {
        "id": mid,
        "question": question,
        "closed": False,
        "volume": volume,
        "outcomePrices": [yes_price, 1 - yes_price],
    }


def test_parse_conditional_question_with_comma():
    parsed = _parse_conditional_question("If Democrats win the House, how many seats will they gain?")
    assert parsed == ("Democrats win the House", "how many seats will they gain?")


def test_count_bucket_detection():
    assert _looks_like_count_bucket("0-4 seats")
    assert _looks_like_count_bucket("10+ seats")
    assert _looks_like_count_bucket("how many states will they win?")
    assert not _looks_like_count_bucket("will bitcoin reach 120k?")


def test_scan_no_signal_without_conditional_group():
    s = ConditionalOutcomeCountAsymmetryStrategy()
    ev = _event("plain", "Plain event", [
        _market("1", "Will Democrats win the House?", 0.42),
        _market("2", "Will Republicans win the House?", 0.58),
    ])
    assert s.scan([ev]) == []


def test_scan_no_signal_when_conditional_sum_is_fair():
    s = ConditionalOutcomeCountAsymmetryStrategy()
    ev = _event("fair", "Conditional seat ranges", [
        _market("p", "Will Democrats win the House?", 0.44),
        _market("1", "If Democrats win the House, 0-4 seats", 0.30),
        _market("2", "If Democrats win the House, 5-9 seats", 0.32),
        _market("3", "If Democrats win the House, 10+ seats", 0.33),
    ])
    assert s.scan([ev]) == []


def test_scan_emits_alert_on_conditional_oversum():
    s = ConditionalOutcomeCountAsymmetryStrategy()
    ev = _event("oversum", "Conditional seat ranges", [
        _market("p", "Will Democrats win the House?", 0.44),
        _market("1", "If Democrats win the House, 0-4 seats", 0.45),
        _market("2", "If Democrats win the House, 5-9 seats", 0.42),
        _market("3", "If Democrats win the House, 10+ seats", 0.34),
    ])
    signals = s.scan([ev])
    assert len(signals) == 1
    sig = signals[0]
    assert sig.strategy == "conditional_outcome_count_asymmetry"
    assert sig.outcome == "NO"
    assert sig.ev_pp > 0
    assert "conditional_sum" in sig.rationale


def test_scan_picks_most_expensive_conditional_child():
    s = ConditionalOutcomeCountAsymmetryStrategy()
    ev = _event("oversum", "Conditional seat ranges", [
        _market("p", "Will Democrats win the House?", 0.44),
        _market("1", "If Democrats win the House, 0-4 seats", 0.32),
        _market("2", "If Democrats win the House, 5-9 seats", 0.50),
        _market("3", "If Democrats win the House, 10+ seats", 0.31),
    ])
    signals = s.scan([ev])
    assert len(signals) == 1
    assert signals[0].market_id.endswith(":2")


def test_scan_populates_parent_info_in_last_check_details():
    s = ConditionalOutcomeCountAsymmetryStrategy()
    ev = _event("oversum", "Conditional seat ranges", [
        _market("p", "Will Democrats win the House?", 0.44),
        _market("1", "If Democrats win the House, 0-4 seats", 0.45),
        _market("2", "If Democrats win the House, 5-9 seats", 0.42),
        _market("3", "If Democrats win the House, 10+ seats", 0.34),
    ])
    s.scan([ev])
    assert len(s.last_check_details) == 1
    detail = s.last_check_details[0]
    assert detail["decision"] == "alert"
    assert detail["parent_question"] == "Will Democrats win the House?"
    assert detail["oversum_pp"] > 0


def test_strategy_is_alert_only():
    s = ConditionalOutcomeCountAsymmetryStrategy()
    assert s.alert_only is True
    assert s.trading_enabled is False
    assert s.promotable is True

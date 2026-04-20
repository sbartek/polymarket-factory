"""Tests for multi-strategy confluence detection."""
from factory.runner import _confluence_key, _build_confluence_map


def test_confluence_key_bare_numeric():
    assert _confluence_key("1234567", "YES") == "1234567:YES"


def test_confluence_key_composite():
    assert _confluence_key("some-slug:1234567", "NO") == "1234567:NO"


def test_confluence_key_normalizes():
    """Bare and composite IDs for the same market should match."""
    bare = _confluence_key("1234567", "YES")
    composite = _confluence_key("some-slug:1234567", "YES")
    assert bare == composite


def test_build_confluence_map_no_overlap():
    rows = [
        {"market_id": "slug-a:111", "outcome": "YES", "strategy": "strat_a"},
        {"market_id": "slug-b:222", "outcome": "NO", "strategy": "strat_b"},
    ]
    m = _build_confluence_map(rows)
    assert m["111:YES"] == 1
    assert m["222:NO"] == 1


def test_build_confluence_map_two_strategies_agree():
    rows = [
        {"market_id": "slug-a:111", "outcome": "YES", "strategy": "strat_a"},
        {"market_id": "slug-a:111", "outcome": "YES", "strategy": "strat_b"},
    ]
    m = _build_confluence_map(rows)
    assert m["111:YES"] == 2


def test_build_confluence_map_bare_and_composite_match():
    """Bare numeric '111' and 'slug:111' should count as same market."""
    rows = [
        {"market_id": "111", "outcome": "NO", "strategy": "strat_a"},
        {"market_id": "slug-a:111", "outcome": "NO", "strategy": "strat_b"},
    ]
    m = _build_confluence_map(rows)
    assert m["111:NO"] == 2


def test_build_confluence_map_different_direction_no_match():
    """Same market but different outcome should NOT be confluence."""
    rows = [
        {"market_id": "slug-a:111", "outcome": "YES", "strategy": "strat_a"},
        {"market_id": "slug-a:111", "outcome": "NO", "strategy": "strat_b"},
    ]
    m = _build_confluence_map(rows)
    assert m.get("111:YES") == 1
    assert m.get("111:NO") == 1


def test_build_confluence_map_same_strategy_no_double_count():
    """Same strategy signaling twice on same market should count as 1."""
    rows = [
        {"market_id": "slug-a:111", "outcome": "YES", "strategy": "strat_a"},
        {"market_id": "111", "outcome": "YES", "strategy": "strat_a"},
    ]
    m = _build_confluence_map(rows)
    assert m["111:YES"] == 1


def test_build_confluence_map_three_strategies():
    rows = [
        {"market_id": "slug:999", "outcome": "NO", "strategy": "s1"},
        {"market_id": "999", "outcome": "NO", "strategy": "s2"},
        {"market_id": "other-slug:999", "outcome": "NO", "strategy": "s3"},
    ]
    m = _build_confluence_map(rows)
    assert m["999:NO"] == 3

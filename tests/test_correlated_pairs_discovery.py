"""
Tests for correlated_pairs pair discovery fixes:
- _topic_keys() returns ALL matching keywords (not just first)
- _discover_pairs() groups by all keywords and deduplicates across groups
"""
from datetime import UTC, datetime, timedelta

from factory.strategies.correlated_pairs import CorrelatedPairsStrategy, _topic_keys


def _market(slug: str, title: str, price: float = 0.4, volume: float = 50_000,
            days: int = 30) -> dict:
    end_date = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "endDate": end_date,
        "markets": [{"closed": False, "outcomePrices": [price, 1 - price]}],
    }


# --- _topic_keys ---

def test_topic_keys_returns_all_matching_keywords():
    keys = _topic_keys("Trump announces end of military operations against Iran by June")
    assert "trump" in keys
    assert "iran" in keys


def test_topic_keys_returns_single_keyword_when_one_match():
    keys = _topic_keys("Will the Iranian regime fall by June?")
    assert "iran" in keys
    assert "trump" not in keys


def test_topic_keys_falls_back_to_first_long_word_when_no_keyword():
    keys = _topic_keys("Rayo Vallecano de Madrid vs. Elche CF")
    assert len(keys) == 1  # no PAIR_KEYWORDS match → first long word


def test_topic_keys_returns_set():
    keys = _topic_keys("Trump China tariff war ceasefire")
    assert isinstance(keys, set)
    assert len(keys) >= 2


# --- _discover_pairs cross-theme grouping ---

def test_discover_pairs_links_trump_and_iran_markets():
    """Trump+Iran market should pair with Iran-only market via shared 'iran' keyword."""
    strat = CorrelatedPairsStrategy()
    markets = [
        _market("trump-iran-end", "Trump announces end of military operations against Iran by June", 0.38),
        _market("iran-regime-fall", "Will the Iranian regime fall by June 30?", 0.14),
        _market("unrelated", "2026 NBA Champion odds", 0.20),
    ]
    pairs = strat._discover_pairs(markets)
    slugs_in_pairs = {(a["slug"], b["slug"]) for a, b in pairs} | {(b["slug"], a["slug"]) for a, b in pairs}
    assert ("trump-iran-end", "iran-regime-fall") in slugs_in_pairs


def test_discover_pairs_deduplicates_across_keyword_groups():
    """A pair matching multiple shared keywords must appear only once."""
    strat = CorrelatedPairsStrategy()
    # Both markets match "trump" and "iran"
    markets = [
        _market("trump-iran-end", "Trump announces end of military operations against Iran by June", 0.38),
        _market("trump-iran-deal", "Will Trump sign Iran deal before July?", 0.25),
    ]
    pairs = strat._discover_pairs(markets)
    assert len(pairs) == 1  # not duplicated once per shared keyword


def test_discover_pairs_respects_max_candidates():
    """Never returns more than MAX_PAIR_CANDIDATES pairs."""
    from factory.strategies.correlated_pairs import MAX_PAIR_CANDIDATES
    strat = CorrelatedPairsStrategy()
    # Many iran-related markets → many possible pairs
    markets = [
        _market(f"iran-{i}", f"Iran event {i} outcome by June", 0.3 + i * 0.05)
        for i in range(10)
    ]
    pairs = strat._discover_pairs(markets)
    assert len(pairs) <= MAX_PAIR_CANDIDATES


def test_discover_pairs_skips_same_slug():
    strat = CorrelatedPairsStrategy()
    m = _market("dup", "Trump Iran deal by July", 0.4)
    pairs = strat._discover_pairs([m, m])
    assert pairs == []


def test_discover_pairs_returns_empty_when_no_eligible_markets():
    strat = CorrelatedPairsStrategy()
    # Low volume — all ineligible
    markets = [_market("low-vol", "Trump Iran deal", 0.4, volume=100)]
    pairs = strat._discover_pairs(markets)
    assert pairs == []

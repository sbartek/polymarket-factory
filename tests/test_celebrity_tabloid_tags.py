"""
Tests for celebrity_tabloid tag-related fixes:
- _market_text() now includes tag labels (regression for silent tag bug)
- _fetch_celebrity_markets() augments base feed and deduplicates by slug
"""
from datetime import UTC, datetime, timedelta

from factory.strategies.celebrity_tabloid import (
    CelebrityTabloidStrategy,
    ENTERTAINMENT_TERMS,
    _market_text,
)


def _market(slug: str, title: str, price: float, volume: float,
            tags: list[dict] | None = None, days: int = 30) -> dict:
    end_date = (datetime.now(UTC) + timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return {
        "slug": slug,
        "title": title,
        "volume24hr": volume,
        "endDate": end_date,
        "category": None,
        "series": None,
        "tags": tags or [],
        "markets": [{"closed": False, "outcomePrices": [price, 1 - price]}],
    }


# --- _market_text tag inclusion ---

def test_market_text_includes_tag_labels():
    ev = _market("test", "Some title", 0.5, 1000, tags=[
        {"slug": "celebrities", "label": "Celebrities"},
        {"slug": "pop-culture", "label": "Pop Culture"},
    ])
    text = _market_text(ev)
    assert "celebrities" in text


def test_market_text_tag_drives_entertainment_match():
    ev = _market("test", "Somebody does something", 0.5, 1000, tags=[
        {"slug": "celebrities", "label": "Celebrities"},
    ])
    text = _market_text(ev)
    assert any(term in text for term in ENTERTAINMENT_TERMS)


def test_market_text_without_tags_has_no_entertainment_match():
    ev = _market("test", "Generic political event happens", 0.5, 1000, tags=[])
    text = _market_text(ev)
    assert not any(term in text for term in ENTERTAINMENT_TERMS)


def test_market_text_with_none_tags_does_not_raise():
    ev = _market("test", "Some event", 0.5, 1000, tags=None)
    ev["tags"] = None
    text = _market_text(ev)
    assert isinstance(text, str)


# --- _fetch_celebrity_markets deduplication ---

def test_fetch_celebrity_markets_deduplicates_slugs(monkeypatch):
    base = [_market("slug-a", "Market A", 0.5, 50000, tags=[])]
    extra = [
        _market("slug-a", "Market A", 0.5, 50000, tags=[]),  # duplicate
        _market("slug-b", "Market B", 0.5, 1000, tags=[{"slug": "celebrities", "label": "Celebrities"}]),
    ]

    strat = CelebrityTabloidStrategy()
    monkeypatch.setattr(
        "factory.strategies.celebrity_tabloid.fetch_by_tag",
        lambda tag, limit=30: extra,
    )

    result = strat._fetch_celebrity_markets(base)
    slugs = [ev["slug"] for ev in result]
    assert slugs.count("slug-a") == 1
    assert "slug-b" in slugs


def test_fetch_celebrity_markets_adds_new_markets(monkeypatch):
    base = [_market("slug-a", "Market A", 0.5, 50000, tags=[])]
    extra = [_market("slug-b", "Market B", 0.5, 1000, tags=[])]

    strat = CelebrityTabloidStrategy()
    monkeypatch.setattr(
        "factory.strategies.celebrity_tabloid.fetch_by_tag",
        lambda tag, limit=30: extra,
    )

    result = strat._fetch_celebrity_markets(base)
    assert len(result) > len(base)
    assert any(ev["slug"] == "slug-b" for ev in result)


def test_fetch_celebrity_markets_tolerates_tag_api_failure(monkeypatch):
    base = [_market("slug-a", "Market A", 0.5, 50000, tags=[])]

    strat = CelebrityTabloidStrategy()
    monkeypatch.setattr(
        "factory.strategies.celebrity_tabloid.fetch_by_tag",
        lambda tag, limit=30: (_ for _ in ()).throw(RuntimeError("network error")),
    )

    result = strat._fetch_celebrity_markets(base)
    assert result == base  # gracefully falls back to base only


# --- end-to-end: celebrity tag market reaches scan candidates ---

def test_scan_finds_candidates_from_celebrity_tagged_market(monkeypatch):
    """A market only in the celebrity tag feed (not base) should become a candidate."""
    base = []
    celebrity_market = _market(
        "zendaya-tom-married",
        "Will Zendaya and Tom Holland get married by December 31?",
        price=0.45,
        volume=500,
        tags=[{"slug": "celebrities", "label": "Celebrities"}],
        days=200,
    )

    strat = CelebrityTabloidStrategy()
    monkeypatch.setattr(
        "factory.strategies.celebrity_tabloid.fetch_by_tag",
        lambda tag, limit=30: [celebrity_market],
    )
    monkeypatch.setattr(strat, "_fetch_gossip_hits", lambda candidate, n=6: [])

    strat.scan(base)

    # At least one candidate should have been evaluated (even if no signal fired)
    assert len(strat.last_check_details) >= 1
    assert strat.last_check_details[0]["market_slug"] == "zendaya-tom-married"

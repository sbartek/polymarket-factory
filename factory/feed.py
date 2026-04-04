"""Polymarket Gamma API wrappers — shared across all strategies."""
import json
import time
import urllib.parse
from datetime import datetime

import requests

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"

FETCH_MAX_RETRIES = 3
FETCH_BACKOFF_BASE = 2  # seconds


def fetch_top(limit: int = 100, retries: int = FETCH_MAX_RETRIES) -> list[dict]:
    params = {"limit": limit, "active": "true", "closed": "false",
              "order": "volume24hr", "ascending": "false"}
    last_error = None
    for attempt in range(retries):
        try:
            resp = requests.get(f"{GAMMA_EVENTS}?{urllib.parse.urlencode(params)}", timeout=15)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last_error = e
            if attempt < retries - 1:
                wait = FETCH_BACKOFF_BASE * (2 ** attempt)
                print(f"  [feed] fetch_top attempt {attempt + 1} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
    raise last_error


def fetch_top_paginated(total: int = 200, page_size: int = 100, retries: int = FETCH_MAX_RETRIES) -> list[dict]:
    """Fetch up to `total` events via paginated Gamma API calls, deduped by slug."""
    all_events: list[dict] = []
    seen_slugs: set[str] = set()
    offset = 0

    while len(all_events) < total:
        params = {"limit": min(page_size, total - len(all_events)), "offset": offset,
                  "active": "true", "closed": "false",
                  "order": "volume24hr", "ascending": "false"}
        last_error = None
        page = None
        for attempt in range(retries):
            try:
                resp = requests.get(f"{GAMMA_EVENTS}?{urllib.parse.urlencode(params)}", timeout=15)
                resp.raise_for_status()
                page = resp.json()
                break
            except (requests.RequestException, ValueError) as e:
                last_error = e
                if attempt < retries - 1:
                    wait = FETCH_BACKOFF_BASE * (2 ** attempt)
                    print(f"  [feed] fetch_top_paginated offset={offset} attempt {attempt + 1} failed: {e} — retrying in {wait}s")
                    time.sleep(wait)
        if page is None:
            if all_events:
                print(f"  [feed] pagination stopped at offset={offset} after error: {last_error} — returning {len(all_events)} events")
                break
            raise last_error

        for ev in page:
            slug = ev.get("slug", "")
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                all_events.append(ev)

        if len(page) < page_size:
            break
        offset += page_size

    return all_events


def fetch_by_tag(tag_slug: str, limit: int = 5) -> list[dict]:
    params = {"tag_slug": tag_slug, "limit": limit, "active": "true",
              "closed": "false", "order": "volume24hr", "ascending": "false"}
    resp = requests.get(f"{GAMMA_EVENTS}?{urllib.parse.urlencode(params)}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_closed(slug: str) -> list[dict]:
    params = {"slug": slug, "closed": "true"}
    resp = requests.get(f"{GAMMA_EVENTS}?{urllib.parse.urlencode(params)}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_yes_price(event: dict) -> float | None:
    for m in event.get("markets", []):
        if m.get("closed"):
            continue
        prices_raw = m.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if prices:
                return float(prices[0])
        except (ValueError, TypeError, IndexError):
            pass
    return None


def get_market_winner(event: dict) -> str | None:
    """Returns 'YES', 'NO', or None if not yet resolved."""
    for m in event.get("markets", []):
        if not m.get("closed"):
            continue
        prices_raw = m.get("outcomePrices", "[]")
        outcomes_raw = m.get("outcomes", '["Yes","No"]')
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
            for i, p in enumerate(prices):
                if float(p) >= 0.99:
                    label = outcomes[i] if i < len(outcomes) else ("Yes" if i == 0 else "No")
                    return label.upper()
        except (ValueError, TypeError, IndexError):
            pass
    return None


def get_submarket_outcome(event: dict, submarket_id: str) -> str | None:
    """
    For multi-outcome events (weather, elections), get the YES/NO resolution
    of a specific sub-market identified by its numeric id.
    """
    for m in event.get("markets", []):
        if str(m.get("id", "")) != str(submarket_id):
            continue
        prices_raw = m.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            yes_price = float(prices[0])
            if yes_price >= 0.99:
                return "YES"
            if yes_price <= 0.01:
                return "NO"
        except (ValueError, TypeError, IndexError):
            pass
    return None


def event_url(ev: dict) -> str:
    slug = ev.get("slug") or ev.get("ticker") or ""
    return f"https://polymarket.com/event/{slug}" if slug else ""


def format_volume(v: float | None) -> str:
    if not v:
        return "?"
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def format_date(end_date: str | None) -> str:
    if not end_date:
        return "?"
    try:
        dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y")
    except (ValueError, AttributeError):
        return end_date[:10]


def markets_to_text(events: list[dict]) -> str:
    lines = []
    for ev in events:
        price = get_yes_price(ev)
        price_pct = f"{price*100:.0f}%" if price is not None else "?"
        vol = format_volume(ev.get("volume24hr") or ev.get("volume"))
        closes = format_date(ev.get("endDate"))
        slug = ev.get("slug", "")
        lines.append(
            f"  slug={slug} | [{price_pct} YES | Vol {vol} | Closes {closes}] {ev.get('title','?')}\n"
            f"    {event_url(ev)}"
        )
    return "\n".join(lines)

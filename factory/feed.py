"""Polymarket Gamma API wrappers — shared across all strategies."""
import json
import urllib.parse
from datetime import datetime

import requests

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"


def fetch_top(limit: int = 100) -> list[dict]:
    params = {"limit": limit, "active": "true", "closed": "false",
              "order": "volume24hr", "ascending": "false"}
    resp = requests.get(f"{GAMMA_EVENTS}?{urllib.parse.urlencode(params)}", timeout=10)
    resp.raise_for_status()
    return resp.json()


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

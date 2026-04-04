#!/usr/bin/env python3
"""Backfill the base rate index from resolved Polymarket events.

Fetches closed events from the Gamma API (paginated, ordered by volume)
and adds them to the TF-IDF kNN index for the base_rate_anchor strategy.

Usage:
    uv run python scripts/backfill_base_rates.py
    uv run python scripts/backfill_base_rates.py --limit 500     # small test
    uv run python scripts/backfill_base_rates.py --limit 5000    # full backfill
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.base_rate_index import BaseRateIndex, DEFAULT_INDEX_PATH

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
PAGE_SIZE = 100
FETCH_RETRIES = 3
BACKOFF_BASE = 2


def fetch_closed_page(offset: int, limit: int = PAGE_SIZE) -> list[dict]:
    params = {
        "closed": "true",
        "limit": limit,
        "offset": offset,
        "order": "volume24hr",
        "ascending": "false",
    }
    url = f"{GAMMA_EVENTS}?{urllib.parse.urlencode(params)}"
    for attempt in range(FETCH_RETRIES):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            if attempt < FETCH_RETRIES - 1:
                wait = BACKOFF_BASE * (2 ** attempt)
                print(f"  retry {attempt + 1}: {e} — waiting {wait}s")
                time.sleep(wait)
            else:
                raise


def resolve_event(ev: dict) -> dict | None:
    """Extract resolution from a closed event. Returns dict for index or None."""
    title = ev.get("title") or ""
    slug = ev.get("slug") or ""
    end_date = (ev.get("endDate") or "")[:10]
    volume = float(ev.get("volume") or ev.get("volume24hr") or 0)

    if not slug or not title:
        return None

    # For single-market events: check resolution from prices
    for m in ev.get("markets", []):
        if not m.get("closed"):
            continue
        prices_raw = m.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            yes_price = float(prices[0])
        except (ValueError, TypeError, IndexError):
            continue

        if yes_price >= 0.99:
            return {"slug": slug, "title": title, "resolved_yes": 1, "end_date": end_date, "volume": volume}
        if yes_price <= 0.01:
            return {"slug": slug, "title": title, "resolved_yes": 0, "end_date": end_date, "volume": volume}

    return None


def backfill_from_local_trades(index: BaseRateIndex) -> int:
    """Add resolved trades from our local SQLite DB."""
    try:
        import sqlite3
        from factory.db import DB_PATH
        if not DB_PATH.exists():
            return 0
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT market_title, event_slug, resolved_outcome "
            "FROM trades WHERE status = 'closed' AND resolved_outcome IS NOT NULL"
        ).fetchall()
        conn.close()
        markets = []
        for row in rows:
            title = row[0] or ""
            slug = row[1] or ""
            resolved = (row[2] or "").upper()
            if not slug or not title:
                continue
            resolved_yes = 1 if resolved == "YES" else 0
            markets.append({"slug": f"local:{slug}", "title": title, "resolved_yes": resolved_yes})
        return index.add_markets(markets)
    except Exception as e:
        print(f"  skipping local trades: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Backfill base rate index from resolved events")
    parser.add_argument("--limit", type=int, default=3000, help="Max events to fetch (default: 3000)")
    parser.add_argument("--index-path", type=Path, default=None, help="Override index file path")
    args = parser.parse_args()

    index_path = args.index_path or DEFAULT_INDEX_PATH
    index = BaseRateIndex.load(index_path)
    print(f"Loaded index: {index.size} existing entries")

    # Fetch from Gamma API
    total_fetched = 0
    total_resolved = 0
    offset = 0
    batch = []

    while total_fetched < args.limit:
        page = fetch_closed_page(offset, min(PAGE_SIZE, args.limit - total_fetched))
        if not page:
            print(f"  no more events at offset {offset}")
            break

        for ev in page:
            resolved = resolve_event(ev)
            if resolved:
                batch.append(resolved)
                total_resolved += 1

        total_fetched += len(page)
        offset += len(page)

        if len(batch) >= 200:
            added = index.add_markets(batch)
            print(f"  fetched {total_fetched} events, {total_resolved} resolved, +{added} new → index={index.size}")
            batch = []

        time.sleep(0.3)  # rate limit courtesy

    if batch:
        added = index.add_markets(batch)
        print(f"  fetched {total_fetched} events, {total_resolved} resolved, +{added} new → index={index.size}")

    # Add local trades
    local_added = backfill_from_local_trades(index)
    if local_added:
        print(f"  +{local_added} from local trades → index={index.size}")

    index.save(index_path)
    print(f"\nDone. Index saved: {index.size} markets at {index_path}")

    # Quick sanity check
    if index.size > 0:
        result = index.query_base_rate("Will the Fed cut interest rates?", k=5)
        print(f"\nSanity check — 'Will the Fed cut interest rates?':")
        print(f"  base_rate={result['base_rate']:.2f}, neighbors={result['n_neighbors']}")
        for n in result["neighbors"][:3]:
            print(f"    {n['similarity']:.3f} | {'YES' if n['resolved_yes'] else 'NO'} | {n['title'][:60]}")


if __name__ == "__main__":
    main()

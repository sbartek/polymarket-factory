#!/usr/bin/env python3
"""Backfill the embedding-based base rate index from resolved Polymarket events.

Fetches closed events from the Gamma API, computes Gemini embeddings,
and stores them in pgvector (base_rate_embeddings table).

Usage:
    uv run python scripts/backfill_embeddings.py
    uv run python scripts/backfill_embeddings.py --limit 500
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

from factory.embedding_index import EmbeddingIndex

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
PAGE_SIZE = 100
FETCH_RETRIES = 3

# Exclude categories where base rates are meaningless (sports results, weather)
# Keep political, policy, crypto, regulatory — these have meaningful base rates
EXCLUDED_KEYWORDS = [
    " vs ", " vs. ",
    "nba", "nhl", "nfl", "mlb", "mls", "ipl", "ufc",
    "cricket", "tennis", "atp", "wta", "boxing", "esport",
    "league of legends", "lol:", "dota", "valorant", "cs2:",
    "grand prix", "formula",
    "temperature", "highest temp", "lowest temp", "weather",
    "bo3", "bo5",
    "total kills", "over/under", "spread:",
    "game 1", "game 2", "game 3",
    "up or down",
]


def _is_excluded(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EXCLUDED_KEYWORDS)


def fetch_page(offset: int, limit: int = PAGE_SIZE) -> list[dict]:
    params = {"closed": "true", "limit": limit, "offset": offset,
              "order": "volume24hr", "ascending": "false"}
    url = f"{GAMMA_EVENTS}?{urllib.parse.urlencode(params)}"
    for attempt in range(FETCH_RETRIES):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < FETCH_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def resolve_event(ev: dict) -> dict | None:
    title = ev.get("title") or ""
    slug = ev.get("slug") or ""
    if not slug or not title:
        return None
    if _is_excluded(title):
        return None
    end_date = (ev.get("endDate") or "")[:10]
    volume = float(ev.get("volume") or 0)

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3000)
    args = parser.parse_args()

    index = EmbeddingIndex()
    print(f"Current index size: {index.size}")

    total_fetched = 0
    total_resolved = 0
    batch: list[dict] = []
    offset = 0

    while total_fetched < args.limit:
        page = fetch_page(offset, min(PAGE_SIZE, args.limit - total_fetched))
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
            print(f"  fetched {total_fetched}, resolved {total_resolved}, +{added} embedded → index={index.size}")
            batch = []

        time.sleep(0.3)

    if batch:
        added = index.add_markets(batch)
        print(f"  fetched {total_fetched}, resolved {total_resolved}, +{added} embedded → index={index.size}")

    print(f"\nDone. Index: {index.size} markets")

    # Sanity check
    if index.size > 0:
        result = index.query_base_rate("Will the Iranian regime fall by June?", k=5)
        print(f"\nSanity check — 'Will the Iranian regime fall by June?':")
        print(f"  base_rate={result['base_rate']:.2f}, neighbors={result['n_neighbors']}")
        for n in result["neighbors"][:3]:
            print(f"    {n['similarity']:.3f} | {'YES' if n['resolved_yes'] else 'NO'} | {n['title'][:60]}")


if __name__ == "__main__":
    main()

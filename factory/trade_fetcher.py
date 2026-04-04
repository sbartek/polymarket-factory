"""
CLOB trade data pipeline — fetch trades from Polymarket Data API.

Run independently: `python -m factory.trade_fetcher [--limit 5000]`
Designed to run every 30 minutes alongside the observer.
Incremental: fetches trades newer than the latest stored timestamp.
No auth required. ~5-10 seconds per run.
"""
import argparse
import time
from datetime import datetime

import requests

from .db import FactoryDB

DATA_API_TRADES = "https://data-api.polymarket.com/trades"
MAX_PER_REQUEST = 1000  # API allows up to 10k, but 1k pages are safer
FETCH_RETRIES = 3
FETCH_BACKOFF = 2


def _fetch_page(after: int, limit: int = MAX_PER_REQUEST) -> list[dict]:
    """Fetch one page of trades from Polymarket Data API."""
    params = {"limit": limit, "after": after}
    last_error = None
    for attempt in range(FETCH_RETRIES):
        try:
            resp = requests.get(DATA_API_TRADES, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last_error = e
            if attempt < FETCH_RETRIES - 1:
                wait = FETCH_BACKOFF * (2 ** attempt)
                print(f"  [trade_fetcher] page attempt {attempt + 1} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
    raise last_error


def fetch_trades(total_limit: int = 5000, db: FactoryDB | None = None) -> tuple[int, int]:
    """
    Fetch trades incrementally from Polymarket Data API.
    Returns (fetched_count, inserted_count).
    """
    if db is None:
        db = FactoryDB()

    run_id = db.start_run(mode="trade_fetcher")
    after_ts = db.get_latest_trade_timestamp()

    all_trades: list[dict] = []
    fetched = 0

    try:
        while fetched < total_limit:
            page_limit = min(MAX_PER_REQUEST, total_limit - fetched)
            page = _fetch_page(after=after_ts, limit=page_limit)
            if not page:
                break

            all_trades.extend(page)
            fetched += len(page)

            # Advance cursor to the latest timestamp in this page
            max_ts = max(int(t.get("timestamp", 0)) for t in page)
            if max_ts <= after_ts:
                break  # no progress, avoid infinite loop
            after_ts = max_ts

            # If we got fewer than requested, we've reached the end
            if len(page) < page_limit:
                break

    except Exception as e:
        print(f"[trade_fetcher] fetch failed after {fetched} trades: {e}")
        db.finish_run(run_id, status="failed", markets_fetched=0,
                      notes=f"trade_fetcher failed: {e}")
        return fetched, 0

    inserted = db.log_market_trades(run_id, all_trades)
    db.finish_run(run_id, status="success", markets_fetched=0,
                  notes=f"trade_fetcher: {fetched} fetched, {inserted} new")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[trade_fetcher] {now} — {fetched} fetched, {inserted} new trades stored")
    return fetched, inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLOB trade data fetcher")
    parser.add_argument("--limit", type=int, default=5000,
                        help="Max trades to fetch per run (default 5000)")
    args = parser.parse_args()
    fetch_trades(total_limit=args.limit)

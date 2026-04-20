"""
Lightweight price observer — fetch market snapshots and write to DB.

Run independently: `python -m factory.observer [--limit 1000]`
Designed to run every 30 minutes for hourly+ price history.
No strategies, no LLM calls, no broker interaction. ~5 seconds per run.
"""
import argparse
import os
from datetime import datetime

from .db import FactoryDB
from .feed import fetch_top_paginated
from .runner import _extract_market_observations


def observe(market_limit: int = 2000):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    db = FactoryDB()
    run_id = db.start_run(mode="observer")

    try:
        markets = fetch_top_paginated(total=market_limit)
    except Exception as e:
        print(f"[observer] fetch failed: {e}")
        db.finish_run(run_id, status="failed", markets_fetched=0, notes=f"fetch failed: {e}")
        return

    markets_fetched = len(markets)
    observations = _extract_market_observations(markets)
    db.log_market_observations(run_id, observations)
    db.finish_run(run_id, status="success", markets_fetched=markets_fetched,
                  notes=f"observer: {len(observations)} observations")
    print(f"[observer] {now} — {len(observations)} observations from {markets_fetched} markets")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lightweight price observer")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    observe(market_limit=args.limit)

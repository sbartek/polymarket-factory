#!/usr/bin/env python3
"""
Kill switch for live trading.

Cancels all open CLOB orders and prints a summary of open live positions.
Does NOT close positions in the DB — those resolve naturally via the CLOB.

Usage:
    uv run python scripts/kill_live.py
    uv run python scripts/kill_live.py --dry-run
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory import clob as clob_api
from factory.db import FactoryDB


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without calling the CLOB")
    args = parser.parse_args()

    db = FactoryDB()
    live_open = [t for t in db.load_trades() if t.get("status") == "open" and t.get("mode") == "live"]

    print(f"Open live positions: {len(live_open)}")
    for t in live_open:
        print(f"  [{t['strategy']}] {t['market_title'][:60]} | ${t['amount_usdc']} | opened {t['opened_at']}")

    if not live_open:
        print("Nothing to cancel.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Would call clob.cancel_all() now.")
        return

    print("\nCancelling all open CLOB orders...")
    try:
        resp = clob_api.cancel_all()
        print(f"Done: {resp}")
    except Exception as e:
        print(f"ERROR calling cancel_all(): {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

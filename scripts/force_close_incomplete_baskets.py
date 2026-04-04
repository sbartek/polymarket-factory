#!/usr/bin/env python3
"""
One-off: force-close spread_arb baskets identified as incomplete open fields.

These baskets hold 2-5 legs of 30+ outcome tournaments (FIFA, NBA, NHL, etc.)
and will almost certainly resolve as 100% losses. Closing them now with NO
to record the loss immediately and clean up the portfolio view.

Root cause: spread_arb._looks_suspicious() had inverted logic that let these
through. Fixed in commit e6c5398. This script handles the existing positions.

Run on each machine that has a local DB copy:
    uv run python scripts/force_close_incomplete_baskets.py
    uv run python scripts/force_close_incomplete_baskets.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory.db import DB_PATH, FactoryDB

DOOMED_SLUGS = {
    # Round 1: incomplete tournament/long-dated fields
    "augusta-national-invitational-winner",
    "2026-nhl-stanley-cup-champion",
    "2026-nba-champion",
    "2026-womens-wimbledon-winner",
    "2026-mens-wimbledon-winner",
    "2026-fifa-world-cup-winner-595",
    "mlb-world-series-champion-2026",
    "mlb-2026-national-league-champion",
    "mls-cup-winner-2026",
    "eurovision-winner-2026",
    "eurovision-2026-televote-winner",
    "next-french-presidential-election",
    "presidential-election-winner-2028",
    "democratic-presidential-nominee-2028",
    # Round 2: remaining pre-fix positions (full clean slate for retest 2026-04-04)
    "when-will-the-dhs-shutdown-end-521",
    "virginia-republican-senate-primary-winner",
    "will-reza-pahlavi-enter-iran-by-june-30",
    "where-will-trump-and-putin-meet-next-584",
    "netanyahu-out-before-2027",
    "next-leader-out-of-power-before-2027-795",
    "iran-leader-end-of-2026",
    "how-many-different-countries-will-israel-strike-in-2026",
    "venezuela-leader-end-of-2026",
    "standx-fdv-above-one-day-after-launch",
}

RUN_ID = "manual-force-close-20260404"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print trades without closing")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()

    db = FactoryDB(path=args.db or DB_PATH)
    trades = [t for t in db.load_trades() if t["strategy"] == "spread_arb" and t["status"] == "open"]
    to_close = [t for t in trades if t["market_id"].split(":")[0] in DOOMED_SLUGS]

    if not to_close:
        print("No matching open trades found — already closed or not present in this DB.")
        return

    total_exposure = sum(float(t.get("amount_usdc") or 0) for t in to_close)
    print(f"{'DRY RUN — ' if args.dry_run else ''}Closing {len(to_close)} trades  exposure=${total_exposure:.2f}\n")

    for t in sorted(to_close, key=lambda x: x["market_id"]):
        amt = float(t.get("amount_usdc") or 0)
        print(f"  {'[dry] ' if args.dry_run else ''}{t['id']}  {t['market_id'][:60]:60s}  ${amt:.2f}")
        if not args.dry_run:
            db.close_trade(t["id"], "NO", run_id_closed=RUN_ID)

    if not args.dry_run:
        remaining = [t for t in db.load_trades() if t["strategy"] == "spread_arb" and t["status"] == "open"]
        print(f"\nDone. Remaining open spread_arb: {len(remaining)}")


if __name__ == "__main__":
    main()

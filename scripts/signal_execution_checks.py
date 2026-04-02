#!/usr/bin/env python3
"""Inspect Phase A execution-reality snapshots logged for generated signals."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.db import DB_PATH
from factory.queries import get_signal_execution_checks, open_db


def _fmt(value, width: int) -> str:
    if value is None:
        s = ""
    elif isinstance(value, float):
        s = f"{value:.2f}"
    else:
        s = str(value)
    return s[:width].ljust(width)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Phase A signal execution snapshots.")
    parser.add_argument("--run-id", default=None, help="Filter by run id")
    parser.add_argument("--strategy", default=None, help="Filter by strategy")
    parser.add_argument("--limit", type=int, default=25, help="Max rows (default: 25)")
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        raise SystemExit(1)

    db = open_db(db_path)
    rows = get_signal_execution_checks(db, run_id=args.run_id, strategy=args.strategy, limit=args.limit)
    print(f"Signal execution checks — {len(rows)} row(s)\n")
    if not rows:
        return

    cols = [
        ("created_at", "time", 19),
        ("strategy", "strategy", 18),
        ("source_confidence", "src", 8),
        ("quote_price", "quote", 6),
        ("fill_price_10", "fill10", 6),
        ("fill_price_50", "fill50", 6),
        ("fill_price_100", "fill100", 7),
        ("ev_after_slippage_10_pp", "ev10", 6),
        ("ev_after_slippage_50_pp", "ev50", 6),
        ("max_size_positive_ev", "max+EV", 6),
        ("market_title", "title", 44),
    ]
    print("  ".join(_fmt(label, width) for _, label, width in cols))
    print("  ".join("-" * width for _, _, width in cols))
    for row in rows:
        print("  ".join(_fmt(row.get(key), width) for key, _, width in cols))


if __name__ == "__main__":
    main()

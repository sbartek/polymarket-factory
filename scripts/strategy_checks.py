#!/usr/bin/env python3
"""Inspect strategy-specific detail tables (spread_arb, resolution_hunter, stale_market, correlated_pairs)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory.db import DB_PATH
from factory.queries import DETAIL_TABLE_GETTERS, open_db

# Column specs: (key, display_label, width)
_COLUMNS: dict[str, list[tuple[str, str, int]]] = {
    "spread_arb": [
        ("created_at", "time", 19),
        ("decision", "decision", 10),
        ("gap_pp", "gap_pp", 7),
        ("score", "score", 6),
        ("leg_count", "legs", 4),
        ("days_to_close", "days", 4),
        ("title", "title", 60),
    ],
    "resolution_hunter": [
        ("created_at", "time", 19),
        ("decision", "decision", 10),
        ("claude_confidence", "conf", 5),
        ("claude_outcome", "outcome", 7),
        ("news_count", "news", 4),
        ("candidate_score", "cscore", 7),
        ("title", "title", 60),
    ],
    "stale_market": [
        ("created_at", "time", 19),
        ("decision", "decision", 10),
        ("topic_key", "topic", 20),
        ("news_count", "news", 4),
        ("candidate_score", "cscore", 7),
        ("title", "title", 50),
    ],
    "correlated_pairs": [
        ("created_at", "time", 19),
        ("decision", "decision", 10),
        ("relationship", "relation", 15),
        ("violation_pp", "viol_pp", 7),
        ("chosen_slug", "chosen", 30),
        ("slug_a", "slug_a", 25),
        ("slug_b", "slug_b", 25),
    ],
}


def _fmt(value, width: int) -> str:
    s = "" if value is None else str(value)
    if isinstance(value, float):
        s = f"{value:.3f}"
    s = s[:width]
    return s.ljust(width)


def print_table(strategy: str, rows: list[dict]) -> None:
    cols = _COLUMNS[strategy]
    header = "  ".join(_fmt(label, w) for _, label, w in cols)
    sep = "  ".join("-" * w for _, _, w in cols)
    print(header)
    print(sep)
    for row in rows:
        line = "  ".join(_fmt(row.get(key), w) for key, _, w in cols)
        print(line)


def main() -> None:
    choices = list(_COLUMNS.keys())
    parser = argparse.ArgumentParser(
        description="Inspect strategy-specific detail tables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Strategies: " + ", ".join(choices),
    )
    parser.add_argument("strategy", choices=choices, help="Which strategy table to inspect")
    parser.add_argument("--run-id", default=None, help="Filter by run id")
    parser.add_argument("--limit", type=int, default=50, help="Max rows (default: 50)")
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        raise SystemExit(1)

    db = open_db(db_path)
    getter = DETAIL_TABLE_GETTERS[args.strategy]
    rows = getter(db, run_id=args.run_id, limit=args.limit)

    run_label = f"run={args.run_id}" if args.run_id else "all runs"
    print(f"Strategy checks: {args.strategy}  ({run_label})  — {len(rows)} row(s)\n")

    if not rows:
        print("No rows found.")
        return

    print_table(args.strategy, rows)


if __name__ == "__main__":
    main()

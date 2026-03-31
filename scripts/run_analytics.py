#!/usr/bin/env python3
"""Summarize recent runs and decision patterns from the factory SQLite database."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.db import DB_PATH
from factory.queries import get_run_analytics, open_db


def _print_counts(title: str, mapping: dict[str, int]) -> None:
    print(f"\n{title}")
    for key, value in mapping.items():
        print(f"  {key:<20} {value:>3}")


def _print_rows(title: str, rows: list[dict], key: str = "reason") -> None:
    print(f"\n{title}")
    if not rows:
        print("  (none)")
        return
    for row in rows:
        label = row.get(key) or "—"
        print(f"  {label:<24} {row.get('cnt', 0):>3}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Show recent run and decision analytics.")
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    parser.add_argument("--runs", type=int, default=20, help="How many recent runs to analyze (default: 20)")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        raise SystemExit(1)

    db = open_db(db_path)
    data = get_run_analytics(db, limit_runs=args.runs)
    runs = data["runs"]

    print(f"Run analytics — last {args.runs} runs")
    print("═" * 60)
    print(f"Observed runs: {len(runs)}")

    _print_counts("By status", data["status_counts"])
    _print_counts("By mode", data["mode_counts"])
    _print_rows("Top decision reasons", data["decision_reason_counts"], key="reason")
    _print_rows("Opens by strategy", data["opens_by_strategy"], key="strategy")
    _print_rows("Skips by strategy", data["skips_by_strategy"], key="strategy")

    if runs:
        print("\nRecent runs")
        for run in runs[:5]:
            print(
                f"  {run['id']}  {run['mode']:<13}  {run['status']:<8}  "
                f"mkts={run.get('markets_fetched') or 0:<3}  "
                f"closed={run.get('closed_count') or 0:<3}  "
                f"new={run.get('new_positions_count') or 0:<3}"
            )


if __name__ == "__main__":
    main()

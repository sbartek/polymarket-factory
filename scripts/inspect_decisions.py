#!/usr/bin/env python3
"""Filter and display decisions from the factory SQLite database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory.db import DB_PATH
from factory.queries import get_decisions, open_db


def _truncate(s: str | None, n: int = 80) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def print_decision(row: dict, show_details: bool = False) -> None:
    ts = (row.get("created_at") or "")[:19]
    dtype = _fmt(row.get("decision_type"), 20)
    dec = _fmt(row.get("decision"), 12)
    strat = _fmt(row.get("strategy") or "—", 18)
    reason = _truncate(row.get("reason"), 70)
    mid = _truncate(row.get("market_id"), 30)

    print(f"  [{ts}] {dtype}{dec} strat={strat} mkt={mid}")
    if reason:
        print(f"          reason: {reason}")
    if show_details and row.get("details_json"):
        try:
            d = json.loads(row["details_json"])
            if d:
                print(f"          details: {json.dumps(d, ensure_ascii=False)[:120]}")
        except Exception:
            pass


def _fmt(value, width: int = 0) -> str:
    s = "" if value is None else str(value)
    return s.ljust(width) if width else s


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect factory decisions.")
    parser.add_argument("--run-id", default=None, help="Filter by run id")
    parser.add_argument("--strategy", default=None, help="Filter by strategy name")
    parser.add_argument("--limit", type=int, default=50, help="Max rows to show (default: 50)")
    parser.add_argument("--details", action="store_true", help="Show details_json payload")
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        raise SystemExit(1)

    db = open_db(db_path)
    rows = get_decisions(db, run_id=args.run_id, strategy=args.strategy, limit=args.limit)

    if not rows:
        print("No decisions found.")
        return

    filters = []
    if args.run_id:
        filters.append(f"run={args.run_id}")
    if args.strategy:
        filters.append(f"strategy={args.strategy}")
    label = "  ".join(filters) or "all"
    print(f"Decisions ({label})  — {len(rows)} row(s), newest first\n")

    for row in rows:
        print_decision(row, show_details=args.details)


if __name__ == "__main__":
    main()

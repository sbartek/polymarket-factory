#!/usr/bin/env python3
"""Show legacy open positions (paused/old strategy baggage) from SQLite-backed trades."""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.db import DB_PATH
from factory.queries import get_legacy_open_positions, open_db


def _group_summary(rows: list[dict], key: str) -> list[tuple[str, int, float]]:
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[row.get(key) or "—"].append(row)
    return sorted(
        [(k, len(v), sum(float(r.get("amount_usdc") or 0) for r in v)) for k, v in groups.items()],
        key=lambda x: x[2],
        reverse=True,
    )


def _print_group(rows: list[tuple[str, int, float]], title: str) -> None:
    print(f"\nBy {title}")
    for name, count, exposure in rows:
        print(f"  {name:<24}  {count:>3} position{'s' if count != 1 else ' '}   ${exposure:>7.2f}")


def _print_positions(rows: list[dict], top_n: int | None = None) -> None:
    shown = rows[:top_n] if top_n else rows
    print(f"\n{'─'*92}")
    print(f"{'opened_at':<20}  {'strategy':<22}  {'window':<11}  {'out':<4}  {'$amt':>6}  market")
    print(f"{'─'*92}")
    for row in shown:
        opened = (row.get("opened_at") or "")[:16]
        strategy = (row.get("strategy") or "")[:22]
        window = (row.get("time_window") or "—")[:11]
        outcome = (row.get("outcome") or "")[:4]
        amount = float(row.get("amount_usdc") or 0)
        title = (row.get("market_title") or "")[:54]
        print(f"{opened:<20}  {strategy:<22}  {window:<11}  {outcome:<4}  ${amount:>5.2f}  {title}")
    if top_n and len(rows) > top_n:
        print(f"\n  … {len(rows) - top_n} more legacy positions")
    print(f"{'─'*92}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Show legacy open positions from the SQLite-backed trade book.")
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    parser.add_argument("--strategy", default=None, help="Filter legacy positions by strategy")
    parser.add_argument("--top-oldest", type=int, default=20, metavar="N", help="Show the N oldest legacy positions (default: 20)")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        raise SystemExit(1)

    db = open_db(db_path)
    rows = get_legacy_open_positions(db, strategy=args.strategy)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    total = sum(float(r.get("amount_usdc") or 0) for r in rows)

    label = f" strategy={args.strategy}" if args.strategy else ""
    print(f"Legacy open positions [{today}]{label}")
    print(f"Total: {len(rows)}  Exposure: ${total:.2f}")
    print("═" * 60)

    if not rows:
        print("No legacy open positions.")
        return

    _print_group(_group_summary(rows, "strategy"), "strategy")
    _print_group(_group_summary(rows, "time_window"), "time window")

    print(f"\nOldest legacy positions (top {args.top_oldest})")
    _print_positions(rows, top_n=args.top_oldest)


if __name__ == "__main__":
    main()

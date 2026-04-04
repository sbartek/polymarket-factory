#!/usr/bin/env python3
"""CLI view of current open book from SQLite-backed trades.

Usage examples:
    uv run python scripts/open_positions.py
    uv run python scripts/open_positions.py --top-oldest 5
    uv run python scripts/open_positions.py --strategy ev_news
    uv run python scripts/open_positions.py --time-window medium
    uv run python scripts/open_positions.py --top-oldest 10 --strategy ev_news
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.db import DB_PATH
from factory.queries import get_open_positions, open_db
from factory.strategy_meta import ACTIVE_STRATEGIES as _ACTIVE_STRATEGIES


def _group_summary(positions: list[dict], key: str) -> list[tuple[str, int, float]]:
    """Return (label, count, total_usdc) sorted by total_usdc descending."""
    groups: dict[str, list] = defaultdict(list)
    for p in positions:
        label = p.get(key) or "—"
        groups[label].append(p)
    return sorted(
        [(k, len(v), sum(p["amount_usdc"] for p in v)) for k, v in groups.items()],
        key=lambda x: x[2],
        reverse=True,
    )


def _lifecycle(p: dict) -> str:
    return "active" if p["strategy"] in _ACTIVE_STRATEGIES else "legacy"


def _print_group_table(rows: list[tuple[str, int, float]], label: str) -> None:
    print(f"\nBy {label}")
    for name, cnt, total in rows:
        print(f"  {name:<24}  {cnt:>3} position{'s' if cnt != 1 else ' '}   ${total:>7.2f}")


def _print_positions_table(positions: list[dict], top_n: int | None = None) -> None:
    shown = positions[:top_n] if top_n else positions
    print(f"\n{'─' * 90}")
    print(f"{'opened_at':<20}  {'strategy':<22}  {'window':<11}  {'out':<4}  {'$amt':>6}  market")
    print("─" * 90)
    for p in shown:
        opened = (p.get("opened_at") or "")[:16]
        strategy = (p.get("strategy") or "")[:22]
        window = (p.get("time_window") or "—")[:11]
        outcome = (p.get("outcome") or "")[:4]
        amt = float(p.get("amount_usdc") or 0)
        title = (p.get("market_title") or "")[:52]
        print(f"{opened:<20}  {strategy:<22}  {window:<11}  {outcome:<4}  ${amt:>5.2f}  {title}")
    if top_n and len(positions) > top_n:
        remaining = len(positions) - top_n
        print(f"\n  … {remaining} more — use --top-oldest {len(positions)} to see all")
    print("─" * 90)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show current open book from SQLite-backed trades.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    parser.add_argument("--strategy", help="Filter by strategy name")
    parser.add_argument("--time-window", dest="time_window", help="Filter by time window")
    parser.add_argument(
        "--top-oldest",
        type=int,
        metavar="N",
        default=None,
        help="Show only the N oldest open positions (default: all)",
    )
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        raise SystemExit(1)

    db = open_db(db_path)
    positions = get_open_positions(db, strategy=args.strategy, time_window=args.time_window)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    total_exposure = sum(p["amount_usdc"] for p in positions)

    filters = []
    if args.strategy:
        filters.append(f"strategy={args.strategy}")
    if args.time_window:
        filters.append(f"time_window={args.time_window}")
    filter_note = f"  [{', '.join(filters)}]" if filters else ""

    print(f"Open positions  [{today}]{filter_note}")
    print(f"Total: {len(positions)}  Exposure: ${total_exposure:.2f}")
    print("═" * 60)

    if not positions:
        print("No open positions.")
        return

    _print_group_table(_group_summary(positions, "strategy"), "strategy")
    _print_group_table(_group_summary(positions, "time_window"), "time window")

    lifecycle_groups: dict[str, list] = defaultdict(list)
    for p in positions:
        lifecycle_groups[_lifecycle(p)].append(p)
    lifecycle_rows = sorted(
        [(k, len(v), sum(p["amount_usdc"] for p in v)) for k, v in lifecycle_groups.items()],
        key=lambda x: x[0],
    )
    _print_group_table(lifecycle_rows, "lifecycle (active vs legacy)")

    n_label = f"oldest {args.top_oldest}" if args.top_oldest else "all"
    print(f"\nPositions — {n_label}, sorted oldest first")
    _print_positions_table(positions, top_n=args.top_oldest)


if __name__ == "__main__":
    main()

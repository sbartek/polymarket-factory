#!/usr/bin/env python3
"""Show the most recent run(s) with status, counts, and a decision summary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory.db import DB_PATH
from factory.queries import get_decisions_summary, get_latest_runs, open_db


def _fmt(value, width: int = 0) -> str:
    s = "" if value is None else str(value)
    return s.ljust(width) if width else s


def print_run(run: dict, db, show_decisions: bool = True) -> None:
    rid = run["id"]
    mode = _fmt(run["mode"], 12)
    status = _fmt(run["status"], 9)
    started = _fmt(run.get("started_at", ""), 20)
    finished = _fmt(run.get("finished_at") or "—", 20)
    mf = run.get("markets_fetched") or 0
    cc = run.get("closed_count") or 0
    npc = run.get("new_positions_count") or 0
    notes = run.get("notes") or ""

    print(f"  id        : {rid}")
    print(f"  mode      : {mode.strip()}")
    print(f"  status    : {status.strip()}")
    print(f"  started   : {started.strip()}")
    print(f"  finished  : {finished.strip()}")
    print(f"  markets   : {mf}  closed: {cc}  new_positions: {npc}")
    if notes:
        print(f"  notes     : {notes}")

    if show_decisions:
        summary = get_decisions_summary(db, run_id=rid)
        if summary:
            print("  decisions :")
            for row in summary:
                print(f"    {row['decision_type']:20s} {row['decision']:15s} ×{row['cnt']}")
        else:
            print("  decisions : (none)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Show the most recent factory run(s).")
    parser.add_argument("-n", type=int, default=1, help="Number of recent runs to show (default: 1)")
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    parser.add_argument("--no-decisions", action="store_true", help="Skip decision summary")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        raise SystemExit(1)

    db = open_db(db_path)
    runs = get_latest_runs(db, n=args.n)

    if not runs:
        print("No runs recorded yet.")
        return

    for i, run in enumerate(runs):
        if i:
            print()
        print(f"Run {i + 1} of {len(runs)}")
        print_run(run, db, show_decisions=not args.no_decisions)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Backfill missing lifecycle/time-window/edge-type metadata on legacy/imported trades."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.db import DB_PATH, FactoryDB


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing trade metadata in SQLite trades table.")
    parser.add_argument("--db", type=Path, default=None, help="Override DB path")
    args = parser.parse_args()

    db_path = args.db or DB_PATH
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        raise SystemExit(1)

    db = FactoryDB(path=db_path)
    updated = db.backfill_trade_metadata()
    print(f"Backfilled trade metadata on {updated} row(s).")


if __name__ == "__main__":
    main()

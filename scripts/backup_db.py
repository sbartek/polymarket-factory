#!/usr/bin/env python3
"""Create a daily backup snapshot of the local SQLite database and CSV trade file with retention cleanup."""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
import shutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "factory.sqlite3"
CSV_PATH = PROJECT_ROOT / "data" / "trades.csv"
BACKUP_DIR = PROJECT_ROOT / "backups"
DEFAULT_KEEP_DAILIES = 14


def make_sqlite_backup(db_path: Path, backup_dir: Path) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    dest = backup_dir / f"factory-{stamp}.sqlite3"
    tmp = backup_dir / f".{dest.name}.tmp"

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    tmp.replace(dest)
    return dest


def make_csv_backup(csv_path: Path, backup_dir: Path) -> Path | None:
    if not csv_path.exists():
        return None
    stamp = datetime.now().strftime("%Y-%m-%d")
    dest = backup_dir / f"trades-{stamp}.csv"
    tmp = backup_dir / f".{dest.name}.tmp"
    shutil.copy2(csv_path, tmp)
    tmp.replace(dest)
    return dest


def prune_old_backups(backup_dir: Path, keep: int):
    removed = []
    for pattern in ("factory-*.sqlite3", "trades-*.csv"):
        files = sorted(backup_dir.glob(pattern))
        if len(files) <= keep:
            continue
        to_remove = files[:-keep]
        for path in to_remove:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to source SQLite DB")
    parser.add_argument("--csv", type=Path, default=CSV_PATH, help="Path to source trades CSV")
    parser.add_argument("--out", type=Path, default=BACKUP_DIR, help="Backup directory")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP_DAILIES, help="How many daily backups to retain")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    db_backup = make_sqlite_backup(args.db, args.out)
    csv_backup = make_csv_backup(args.csv, args.out)
    removed = prune_old_backups(args.out, args.keep)

    print(f"Created DB backup: {db_backup}")
    if csv_backup:
        print(f"Created CSV backup: {csv_backup}")
    else:
        print("CSV source not found; skipped CSV backup.")

    if removed:
        print("Removed old backups:")
        for path in removed:
            print(f"  - {path}")
    else:
        print("No old backups removed.")


if __name__ == "__main__":
    main()

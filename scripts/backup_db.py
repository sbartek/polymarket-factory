#!/usr/bin/env python3
"""Create a daily backup snapshot of the local SQLite database with retention cleanup.

Optionally uploads a gzipped copy to a GCS bucket (requires gcloud CLI).
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "factory.sqlite3"
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


def gzip_file(src: Path) -> Path:
    """Gzip a file in-place, returning the .gz path."""
    gz_path = src.with_suffix(src.suffix + ".gz")
    with open(src, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    return gz_path


def upload_to_gcs(local_path: Path, bucket: str) -> bool:
    """Upload a file to GCS. Returns True on success."""
    dest = f"gs://{bucket}/{local_path.name}"
    gcloud = shutil.which("gcloud")
    if not gcloud:
        print(f"  [backup] gcloud not found — skipping GCS upload")
        return False
    try:
        result = subprocess.run(
            [gcloud, "storage", "cp", str(local_path), dest],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  [backup] GCS upload failed: {result.stderr.strip()[:200]}")
            return False
        print(f"  [backup] Uploaded to {dest}")
        return True
    except Exception as e:
        print(f"  [backup] GCS upload error: {e}")
        return False


def prune_old_backups(backup_dir: Path, keep: int):
    removed = []
    for pattern in ("factory-*.sqlite3",):
        files = sorted(backup_dir.glob(pattern))
        if len(files) <= keep:
            continue
        to_remove = files[:-keep]
        for path in to_remove:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


GCS_BUCKET = "pplayouts-factory-backups"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Path to source SQLite DB")
    parser.add_argument("--out", type=Path, default=BACKUP_DIR, help="Backup directory")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP_DAILIES, help="How many daily backups to retain")
    parser.add_argument("--no-gcs", action="store_true", help="Skip GCS upload")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    db_backup = make_sqlite_backup(args.db, args.out)
    removed = prune_old_backups(args.out, args.keep)

    print(f"Created DB backup: {db_backup}")

    if removed:
        print("Removed old backups:")
        for path in removed:
            print(f"  - {path}")
    else:
        print("No old backups removed.")

    if not args.no_gcs:
        gz_path = gzip_file(db_backup)
        print(f"Compressed: {gz_path} ({gz_path.stat().st_size / 1024 / 1024:.1f} MB)")
        upload_to_gcs(gz_path, GCS_BUCKET)
        gz_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

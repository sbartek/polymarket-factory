#!/usr/bin/env python3
"""Create a new improvement change record from the template with a generated ID."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "improvement" / "templates" / "change_record.md"
OUT_DIR = PROJECT_ROOT / "improvement" / "changes"


def slugify(text: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())[:60]


def next_sequence(date_prefix: str) -> int:
    existing = sorted(OUT_DIR.glob(f"CR-{date_prefix}-*.md"))
    nums = []
    for path in existing:
        parts = path.stem.split("-")
        if len(parts) >= 3 and parts[2].isdigit():
            nums.append(int(parts[2]))
    return (max(nums) + 1) if nums else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new change-record file from template.")
    parser.add_argument("title", help="Short descriptive title for the change record")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y%m%d")
    seq = next_sequence(today)
    change_id = f"CR-{today}-{seq:03d}"
    slug = slugify(args.title)
    out_path = OUT_DIR / f"{change_id}-{slug}.md"

    text = TEMPLATE.read_text()
    text = text.replace("CR-YYYYMMDD-xxx", change_id)
    text = text.replace("YYYY-MM-DD", datetime.now().strftime("%Y-%m-%d"), 1)
    text = text.replace("What changed?", args.title)
    out_path.write_text(text)
    print(out_path)


if __name__ == "__main__":
    main()

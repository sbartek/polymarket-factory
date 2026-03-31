#!/usr/bin/env python3
"""Show active improvement-harness experiment threads and quick evidence pointers."""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHANGES_DIR = PROJECT_ROOT / "improvement" / "changes"
EXPERIMENTS_DIR = PROJECT_ROOT / "improvement" / "experiments"
REVIEWS_DIR = PROJECT_ROOT / "improvement" / "reviews"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_field(text: str, field: str) -> str:
    m = re.search(rf"- \*\*{re.escape(field)}:\*\*\s*(.+)", text)
    return m.group(1).strip() if m else ""


def _find_active_change_records() -> list[dict]:
    rows = []
    for path in sorted(CHANGES_DIR.glob("CR-*.md")):
        text = _read(path)
        status = _extract_field(text, "status")
        if status != "running":
            continue
        rows.append({
            "path": path,
            "change_id": _extract_field(text, "change_id") or path.stem,
            "date": _extract_field(text, "date"),
            "component": _extract_field(text, "component"),
            "owner": _extract_field(text, "owner"),
            "summary": re.search(r"## Summary\n\n(.+?)(\n##|\Z)", text, re.S).group(1).strip().replace("\n", " ") if "## Summary" in text else "",
        })
    return rows


def _related_experiments(change_id: str) -> list[Path]:
    matches = []
    for path in sorted(EXPERIMENTS_DIR.glob("EX-*.md")):
        text = _read(path)
        if _extract_field(text, "related_change_id") == change_id:
            matches.append(path)
    return matches


def _related_reviews(change_id: str) -> list[Path]:
    matches = []
    for path in sorted(REVIEWS_DIR.glob("RV-*.md")):
        text = _read(path)
        related = _extract_field(text, "related_change_ids")
        if change_id in related:
            matches.append(path)
    return matches


def main() -> None:
    rows = _find_active_change_records()
    print("Active experiment threads")
    print("═" * 72)
    if not rows:
        print("No active change records with status=running.")
        return

    for row in rows:
        ex_paths = _related_experiments(row["change_id"])
        rv_paths = _related_reviews(row["change_id"])
        print(f"{row['change_id']}  [{row['date']}]")
        print(f"  component: {row['component']}")
        print(f"  owner: {row['owner']}")
        if row['summary']:
            print(f"  summary: {row['summary'][:120]}")
        if ex_paths:
            print("  experiments:")
            for p in ex_paths:
                print(f"    - {p.name}")
        if rv_paths:
            print("  reviews:")
            for p in rv_paths:
                print(f"    - {p.name}")
        print()


if __name__ == "__main__":
    main()

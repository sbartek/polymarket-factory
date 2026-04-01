#!/usr/bin/env python3
"""Build a self-contained static dashboard bundle from dashboard/ + dashboard-data/."""
from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_SRC = PROJECT_ROOT / "dashboard"
DATA_SRC = PROJECT_ROOT / "dashboard-data"
DIST_DIR = PROJECT_ROOT / "dashboard-dist"


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path) -> int:
    count = 0
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    return count


def main() -> None:
    if not DASHBOARD_SRC.exists():
        raise SystemExit("dashboard/ not found")
    if not DATA_SRC.exists():
        raise SystemExit("dashboard-data/ not found; run scripts/export_dashboard_data.py first")

    reset_dir(DIST_DIR)
    site_count = copy_tree(DASHBOARD_SRC, DIST_DIR)
    data_count = copy_tree(DATA_SRC, DIST_DIR / "data")

    print("Built dashboard bundle:")
    print(f"- site files: {site_count}")
    print(f"- data files: {data_count}")
    print(f"- output: {DIST_DIR}")
    print("Open locally with a static server rooted at dashboard-dist/.")


if __name__ == "__main__":
    main()

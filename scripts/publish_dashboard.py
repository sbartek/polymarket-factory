#!/usr/bin/env python3
"""Build and publish the static dashboard bundle into a target directory/repo checkout."""
from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = PROJECT_ROOT / "scripts" / "export_dashboard_data.py"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_dashboard.py"
DIST_DIR = PROJECT_ROOT / "dashboard-dist"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, check=True)


def ensure_clean_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sync_dirs(src: Path, dst: Path) -> bool:
    """Mirror src into dst. Returns True if changes were made."""
    changed = False
    ensure_clean_dir(dst)

    src_files = {p.relative_to(src) for p in src.rglob('*') if p.is_file()}
    dst_files = {p.relative_to(dst) for p in dst.rglob('*') if p.is_file() and '.git' not in p.parts}

    for rel in sorted(dst_files - src_files):
        (dst / rel).unlink()
        changed = True

    for rel in sorted(src_files):
        s = src / rel
        d = dst / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if not d.exists() or not filecmp.cmp(s, d, shallow=False):
            shutil.copy2(s, d)
            changed = True

    # prune empty dirs
    for directory in sorted((p for p in dst.rglob('*') if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

    return changed


def git_has_changes(repo: Path) -> bool:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True)
    return bool(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish dashboard bundle into a target checkout/directory")
    parser.add_argument("target", help="Path to dashboard publishing checkout or directory")
    parser.add_argument("--skip-export", action="store_true", help="Do not rerun export/build before syncing")
    parser.add_argument("--commit", action="store_true", help="Commit target repo changes after syncing")
    parser.add_argument("--push", action="store_true", help="Push target repo after commit")
    parser.add_argument("--message", default="dashboard: update static bundle", help="Commit message when --commit is used")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()

    if not args.skip_export:
        run(["uv", "run", "python", "-m", "scripts.export_dashboard_data"])
        run(["uv", "run", "python", "-m", "scripts.build_dashboard"])

    if not DIST_DIR.exists():
        raise SystemExit("dashboard-dist/ not found. Build the dashboard first.")

    changed = sync_dirs(DIST_DIR, target)
    print(f"Synced dashboard-dist -> {target}")
    print(f"Changed: {'yes' if changed else 'no'}")

    git_dir = target / ".git"
    if args.commit:
        if not git_dir.exists():
            raise SystemExit("--commit requested but target is not a git repo checkout")
        if git_has_changes(target):
            run(["git", "add", "."], cwd=target)
            run(["git", "commit", "-m", args.message], cwd=target)
            print("Committed dashboard bundle changes.")
        else:
            print("No git changes to commit.")

    if args.push:
        if not git_dir.exists():
            raise SystemExit("--push requested but target is not a git repo checkout")
        run(["git", "push"], cwd=target)
        print("Pushed dashboard bundle changes.")


if __name__ == "__main__":
    main()

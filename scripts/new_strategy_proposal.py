#!/usr/bin/env python3
"""Create a new strategy proposal draft from plain-language text."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "improvement" / "templates" / "strategy_proposal.md"
OUT_DIR = PROJECT_ROOT / "improvement" / "proposals"


def slugify(text: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())[:60]


def next_sequence(date_prefix: str) -> int:
    existing = sorted(OUT_DIR.glob(f"PR-{date_prefix}-*.md"))
    nums = []
    for path in existing:
        parts = path.stem.split("-")
        if len(parts) >= 3 and parts[2].isdigit():
            nums.append(int(parts[2]))
    return (max(nums) + 1) if nums else 1


def infer_name(text: str) -> str:
    words = [w.lower() for w in ''.join(ch if ch.isalnum() else ' ' for ch in text).split() if len(w) >= 4]
    return '_'.join(words[:3]) if words else 'new_strategy'


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new strategy proposal markdown draft.")
    parser.add_argument("text", help="Plain-language strategy idea")
    parser.add_argument("--proposed-by", default="Daniel / Pawel", help="Human proposer(s)")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y%m%d")
    today_human = datetime.now().strftime("%Y-%m-%d")
    seq = next_sequence(today)
    proposal_id = f"PR-{today}-{seq:03d}"
    slug = slugify(args.text[:80])
    out_path = OUT_DIR / f"{proposal_id}-{slug}.md"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    inferred_name = infer_name(args.text)
    text = TEMPLATE.read_text()
    text = text.replace("PR-YYYYMMDD-xxx", proposal_id)
    text = text.replace("YYYY-MM-DD", today_human, 1)
    text = text.replace("- **proposed_by:**", f"- **proposed_by:** {args.proposed_by}")
    text = text.replace("What did the humans propose?", args.text)
    text = text.replace("- **proposed_name:**", f"- **proposed_name:** {inferred_name}")
    out_path.write_text(text)

    print(out_path)
    print()
    print("Draft created. Next step: review in chat and reply with approve / revise / reject / park.")


if __name__ == "__main__":
    main()

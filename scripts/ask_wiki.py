#!/usr/bin/env python3
"""
Q&A over the polymarket factory wiki.

Loads all wiki pages as context, then answers questions with Claude.
Every answer is optionally filed back into the wiki.

Usage:
    uv run python scripts/ask_wiki.py "which strategies have the best signal quality?"
    uv run python scripts/ask_wiki.py "what should I focus on this week?"
    uv run python scripts/ask_wiki.py "why is spread_arb ROI so bad?" --file-back
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.claude import call_gemini as call_llm

WIKI_DIR = Path(__file__).resolve().parents[1] / "wiki"
TODAY = datetime.now(UTC).strftime("%Y-%m-%d")


def _load_wiki() -> str:
    pages = []
    for md in sorted(WIKI_DIR.rglob("*.md")):
        rel = md.relative_to(WIKI_DIR)
        content = md.read_text()
        pages.append(f"## [{rel}]\n\n{content}")
    return "\n\n---\n\n".join(pages)


def ask(question: str, file_back: bool = False) -> str:
    wiki = _load_wiki()
    if not wiki:
        print("Wiki is empty — run update_wiki.py first.")
        sys.exit(1)

    prompt = f"""You are a knowledgeable assistant for a Polymarket paper-trading system.
Below is the full wiki — living documentation maintained by the system itself.

=== WIKI ===
{wiki}
=== END WIKI ===

Question: {question}

Answer concisely and specifically. Reference specific strategies, numbers, or wiki sections when relevant.
If the wiki doesn't have enough data to answer confidently, say so and suggest what data would help.
"""

    answer = call_llm(prompt, max_tokens=1000)

    print(f"\nQ: {question}")
    print(f"\nA: {answer}")

    if file_back:
        _file_back(question, answer)

    return answer


def _file_back(question: str, answer: str):
    """Append Q&A to wiki/meta/qa_log.md so knowledge compounds."""
    qa_log = WIKI_DIR / "meta" / "qa_log.md"
    entry = f"\n## {TODAY}\n**Q:** {question}\n\n**A:** {answer}\n"
    with open(qa_log, "a") as f:
        f.write(entry)
    print(f"\n[filed back → wiki/meta/qa_log.md]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", help="Question to ask")
    parser.add_argument("--file-back", action="store_true", help="Append answer to wiki/meta/qa_log.md")
    args = parser.parse_args()

    if not args.question:
        print("Usage: uv run python scripts/ask_wiki.py \"your question\" [--file-back]")
        sys.exit(1)

    ask(args.question, file_back=args.file_back)


if __name__ == "__main__":
    main()

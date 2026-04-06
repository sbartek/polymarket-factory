#!/usr/bin/env python3
"""
Wiki updater — feeds DB data to Claude and updates wiki/ markdown pages.

Follows the Karpathy pattern: raw data in → LLM organizes → living wiki.
Every answer makes the wiki smarter.

Usage:
    uv run python scripts/update_wiki.py                  # update all pages
    uv run python scripts/update_wiki.py --page strategies # only strategy pages
    uv run python scripts/update_wiki.py --page patterns
    uv run python scripts/update_wiki.py --page meta
    uv run python scripts/update_wiki.py --dry-run        # print prompts, no writes
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.claude import call_gemini as call_llm
from factory.db import FactoryDB
from factory.strategy_meta import ACTIVE_STRATEGIES, strategy_metadata

WIKI_DIR = Path(__file__).resolve().parents[1] / "wiki"
TODAY = datetime.now(UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------

def _load_all_data(db: FactoryDB) -> dict:
    trades = db.load_trades()
    meta = strategy_metadata()

    closed = [t for t in trades if t["status"] == "closed"]
    open_ = [t for t in trades if t["status"] == "open"]

    by_strategy: dict[str, dict] = {}
    all_strategies = set(t["strategy"] for t in trades)

    for name in all_strategies:
        s_trades = [t for t in trades if t["strategy"] == name]
        s_closed = [t for t in s_trades if t["status"] == "closed"]
        s_open = [t for t in s_trades if t["status"] == "open"]
        s_meta = meta.get(name, {})

        wins = [t for t in s_closed if float(t.get("pnl_usdc") or 0) > 0]
        staked = sum(float(t.get("amount_usdc") or 0) for t in s_closed)
        pnl = sum(float(t.get("pnl_usdc") or 0) for t in s_closed)
        open_exp = sum(float(t.get("amount_usdc") or 0) for t in s_open)

        recent_closed = sorted(s_closed, key=lambda t: t.get("closed_at") or "", reverse=True)[:5]
        recent_signals_raw = []
        with db._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signals WHERE strategy = ? ORDER BY created_at DESC LIMIT 10",
                (name,),
            ).fetchall()
            recent_signals_raw = [dict(r) for r in rows]

        by_strategy[name] = {
            "name": name,
            "lifecycle": "active" if name in ACTIVE_STRATEGIES else "legacy",
            "edge_type": s_meta.get("edge_type", "other"),
            "time_window": s_meta.get("time_window", "unknown"),
            "open_positions": len(s_open),
            "open_exposure_usdc": round(open_exp, 2),
            "closed_trades": len(s_closed),
            "wins": len(wins),
            "win_rate": round(len(wins) / len(s_closed), 3) if s_closed else None,
            "total_staked": round(staked, 2),
            "pnl_usdc": round(pnl, 2),
            "roi": round(pnl / staked, 3) if staked else None,
            "recent_closed": [
                {
                    "title": t.get("market_title", "")[:80],
                    "outcome": t.get("outcome"),
                    "resolved": t.get("resolved_outcome"),
                    "pnl": float(t.get("pnl_usdc") or 0),
                    "closed_at": t.get("closed_at", "")[:10],
                }
                for t in recent_closed
            ],
            "recent_signals": [
                {
                    "title": r.get("market_title", "")[:80],
                    "ev_pp": r.get("ev_pp"),
                    "confidence": r.get("confidence"),
                    "decision": r.get("decision_status"),
                    "created_at": (r.get("created_at") or "")[:10],
                }
                for r in recent_signals_raw
            ],
        }

    with db._connect() as conn:
        recent_runs = [dict(r) for r in conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 20"
        ).fetchall()]
        skip_reasons = [dict(r) for r in conn.execute(
            """SELECT strategy, reason, COUNT(*) as cnt
               FROM decisions WHERE decision_type='cap_check' AND decision='skip'
               GROUP BY strategy, reason ORDER BY cnt DESC LIMIT 20"""
        ).fetchall()]
        top_ev_signals = [dict(r) for r in conn.execute(
            """SELECT strategy, market_title, ev_pp, confidence, created_at
               FROM signals ORDER BY ev_pp DESC LIMIT 20"""
        ).fetchall()]

    # Ensure all active strategies appear even if they have no trades yet
    for name in ACTIVE_STRATEGIES:
        if name not in by_strategy:
            s_meta = meta.get(name, {})
            by_strategy[name] = {
                "name": name,
                "lifecycle": "active",
                "edge_type": s_meta.get("edge_type", "other"),
                "time_window": s_meta.get("time_window", "unknown"),
                "open_positions": 0,
                "open_exposure_usdc": 0.0,
                "closed_trades": 0,
                "wins": 0,
                "win_rate": None,
                "total_staked": 0.0,
                "pnl_usdc": 0.0,
                "roi": None,
                "recent_closed": [],
                "recent_signals": [],
            }

    return {
        "as_of": TODAY,
        "total_open": len(open_),
        "total_closed": len(closed),
        "total_pnl": round(sum(float(t.get("pnl_usdc") or 0) for t in closed), 2),
        "total_staked": round(sum(float(t.get("amount_usdc") or 0) for t in closed), 2),
        "by_strategy": by_strategy,
        "recent_runs": recent_runs[:10],
        "skip_reasons": skip_reasons,
        "top_ev_signals": top_ev_signals,
    }


# ---------------------------------------------------------------------------
# Wiki page generators
# ---------------------------------------------------------------------------

def _update_strategy_page(name: str, data: dict, dry_run: bool = False):
    s = data["by_strategy"].get(name)
    if s is None:
        return

    prompt = f"""You are maintaining a living wiki page for the Polymarket trading strategy "{name}".

Here is the current performance data as of {data['as_of']}:

{json.dumps(s, indent=2)}

Write a concise wiki page in markdown with these sections:
1. **Status** — one line: lifecycle (active/legacy), edge type, time window, verdict (kill/watch/keep based on WR and ROI)
2. **Performance** — key numbers: open positions, closed trades, win rate, ROI, total P&L
3. **Recent Closed Trades** — brief table or list of last 5 closed trades with outcome and P&L
4. **Recent Signals** — what the strategy has been seeing lately (last 10 signals)
5. **Observations** — 2-4 bullet points of patterns you notice in the data. Be specific and critical.
6. **Open Questions** — 1-3 things that are unclear or worth investigating

Be concise, factual, and critical. Don't pad with fluff. If performance is poor, say so directly.
Start with: `# {name}\n_Last updated: {data['as_of']}_\n`

OUTPUT ONLY THE MARKDOWN. No preamble, no commentary, no "here is the page" intro.
"""

    if dry_run:
        print(f"\n--- PROMPT for wiki/strategies/{name}.md ---")
        print(prompt[:500] + "...")
        return

    print(f"  Updating wiki/strategies/{name}.md...")
    content = call_llm(prompt, max_tokens=1500)
    path = WIKI_DIR / "strategies" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _update_patterns_page(data: dict, dry_run: bool = False):
    strategies_summary = {
        name: {k: v for k, v in s.items() if k not in ("recent_closed", "recent_signals")}
        for name, s in data["by_strategy"].items()
    }

    prompt = f"""You are maintaining a living wiki page about cross-strategy patterns for a Polymarket trading system.

Performance data as of {data['as_of']}:

Strategy summaries:
{json.dumps(strategies_summary, indent=2)}

Most common skip reasons (cap hits):
{json.dumps(data['skip_reasons'], indent=2)}

Top EV signals ever generated:
{json.dumps(data['top_ev_signals'][:10], indent=2)}

Write a concise wiki page in markdown with these sections:
1. **What's Working** — edge types / time windows / strategies with positive signals
2. **What's Not Working** — patterns across losing strategies. Be specific.
3. **Signal Quality** — observations about EV accuracy, confidence calibration
4. **Capacity Constraints** — where exposure caps are being hit and why
5. **Hypotheses to Test** — 2-3 concrete, testable ideas based on the patterns

Be analytical and direct. Look for non-obvious patterns across strategies.
Start with: `# Cross-Strategy Patterns\n_Last updated: {data['as_of']}_\n`

OUTPUT ONLY THE MARKDOWN. No preamble, no commentary, no "here is the page" intro.
"""

    if dry_run:
        print(f"\n--- PROMPT for wiki/patterns/cross_strategy.md ---")
        print(prompt[:500] + "...")
        return

    print("  Updating wiki/patterns/cross_strategy.md...")
    content = call_llm(prompt, max_tokens=1500)
    path = WIKI_DIR / "patterns" / "cross_strategy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _update_meta_page(data: dict, dry_run: bool = False):
    prompt = f"""You are maintaining the top-level meta wiki page for a Polymarket paper-trading system.

System state as of {data['as_of']}:
- Total open positions: {data['total_open']}
- Total closed trades: {data['total_closed']}
- Total P&L: ${data['total_pnl']}
- Total staked: ${data['total_staked']}
- Overall ROI: {round(data['total_pnl'] / data['total_staked'] * 100, 1) if data['total_staked'] else 0}%

Strategy roster:
{json.dumps([
    {
        "name": s["name"],
        "lifecycle": s["lifecycle"],
        "verdict": "keep" if (s["win_rate"] or 0) >= 0.5 and (s["roi"] or 0) > 0
                   else "kill" if (s["closed_trades"] >= 5 and ((s["win_rate"] or 1) < 0.3 or (s["roi"] or 0) < -0.1))
                   else "watch",
        "closed": s["closed_trades"],
        "roi": s["roi"],
    }
    for s in data["by_strategy"].values()
], indent=2)}

Recent run cadence: {len(data['recent_runs'])} runs in DB, latest: {data['recent_runs'][0]['started_at'][:16] if data['recent_runs'] else 'none'}

Write a concise top-level wiki page in markdown:
1. **System Health** — one paragraph on overall state
2. **Strategy Roster** — quick table: name | verdict | closed trades | ROI
3. **Current Focus** — what should we be paying attention to right now?
4. **Next Actions** — 3-5 concrete next steps ranked by impact
5. **Open Questions** — biggest unknowns in the system

Be direct. This is the page someone reads first to understand the system state.
Start with: `# Polymarket Factory — System Overview\n_Last updated: {data['as_of']}_\n`

OUTPUT ONLY THE MARKDOWN. No preamble, no commentary, no "here is the page" intro.
"""

    if dry_run:
        print(f"\n--- PROMPT for wiki/meta/overview.md ---")
        print(prompt[:500] + "...")
        return

    print("  Updating wiki/meta/overview.md...")
    content = call_llm(prompt, max_tokens=1500)
    path = WIKI_DIR / "meta" / "overview.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", choices=["strategies", "patterns", "meta", "all"], default="all")
    parser.add_argument("--strategy", help="Only update this strategy (with --page strategies)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Loading data from DB...")
    db = FactoryDB()
    data = _load_all_data(db)
    print(f"  {len(data['by_strategy'])} strategies, {data['total_closed']} closed trades, {data['total_open']} open\n")

    if not data["by_strategy"] and data["total_closed"] == 0 and data["total_open"] == 0:
        print("DB appears empty — no wiki pages to generate. Skipping.")
        return

    if args.page in ("strategies", "all"):
        strategies = [args.strategy] if args.strategy else list(data["by_strategy"].keys())
        print(f"Updating {len(strategies)} strategy pages...")
        for name in sorted(strategies):
            _update_strategy_page(name, data, dry_run=args.dry_run)

    if args.page in ("patterns", "all"):
        print("\nUpdating patterns page...")
        _update_patterns_page(data, dry_run=args.dry_run)

    if args.page in ("meta", "all"):
        print("\nUpdating meta overview...")
        _update_meta_page(data, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\nWiki updated at {WIKI_DIR}")


if __name__ == "__main__":
    main()

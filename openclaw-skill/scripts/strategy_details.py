#!/usr/bin/env python3
"""
/details <strategy> — returns compact SQLite-backed strategy details for WhatsApp.
Called by the PPLayouts OpenClaw skill.
Usage: uv run openclaw-skill/scripts/strategy_details.py <strategy_name>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from factory.broker import PaperBroker
from factory.queries import (
    get_correlated_pairs_checks,
    get_decisions,
    get_latest_runs,
    get_resolution_hunter_checks,
    get_spread_arb_baskets,
    get_stale_market_checks,
    open_db,
)
from factory.strategy_meta import ACTIVE_STRATEGIES, strategy_metadata

STRATEGY_ALIASES = {
    "ev": "ev_news",
    "fade": "fade_certainty",
    "weather": "weather_edge",
    "arb": "spread_arb",
    "resolution": "resolution_hunter",
    "hunter": "resolution_hunter",
    "stale": "stale_market",
    "corr": "correlated_pairs",
    "pairs": "correlated_pairs",
}

VALID_STRATEGIES = [
    "ev_news",
    "fade_certainty",
    "weather_edge",
    "spread_arb",
    "resolution_hunter",
    "stale_market",
    "correlated_pairs",
]


def load_trades(strategy: str) -> list[dict]:
    return [t for t in PaperBroker(export_csv=False).get_all_trades() if t["strategy"] == strategy]


def _recent_checks(db, strategy: str, limit: int = 4) -> list[dict]:
    if strategy == "spread_arb":
        return get_spread_arb_baskets(db, limit=limit)
    if strategy == "resolution_hunter":
        return get_resolution_hunter_checks(db, limit=limit)
    if strategy == "stale_market":
        return get_stale_market_checks(db, limit=limit)
    if strategy == "correlated_pairs":
        return get_correlated_pairs_checks(db, limit=limit)
    return []


def _format_check(strategy: str, row: dict) -> str:
    if strategy == "spread_arb":
        return f"  {row.get('decision','?')}: gap {float(row.get('gap_pp') or 0):.1f}pp | {str(row.get('title') or '?')[:44]}"
    if strategy == "resolution_hunter":
        conf = row.get("claude_confidence")
        conf_s = f"{int(conf)}%" if conf is not None else "-"
        return f"  {row.get('decision','?')}: conf {conf_s} | {str(row.get('title') or '?')[:44]}"
    if strategy == "stale_market":
        return f"  {row.get('decision','?')}: {row.get('topic_key') or '?'} | {str(row.get('title') or '?')[:44]}"
    if strategy == "correlated_pairs":
        return f"  {row.get('decision','?')}: {row.get('relationship') or '?'} | {(row.get('chosen_slug') or '?')[:38]}"
    return f"  {row}"


def _top_skip_reasons(db, strategy: str, limit: int = 3) -> list[str]:
    rows = get_decisions(db, strategy=strategy, limit=25)
    skip_rows = [r for r in rows if r.get("decision") == "skip"]
    reasons = []
    seen = set()
    for row in skip_rows:
        reason = row.get("reason") or row.get("decision_type") or "skip"
        if reason in seen:
            continue
        seen.add(reason)
        reasons.append(reason)
        if len(reasons) >= limit:
            break
    return reasons


def _format_trade(t: dict) -> str:
    status = t["status"]
    outcome = t["outcome"]
    title = t["market_title"][:52]
    closes = t["closes"][:10] if t.get("closes") else "?"
    amount = float(t["amount_usdc"])
    if status == "open":
        mp = float(t["entry_price"]) * 100
        return f"  OPEN {outcome} {title}\n       ${amount:.1f} @ {mp:.0f}% | closes {closes}"
    pnl = float(t["pnl_usdc"])
    sign = "✅" if pnl > 0 else "❌"
    resolved = t.get("resolved_outcome", "?")
    return f"  {sign} {outcome} {title}\n       ${amount:.1f} → {pnl:+.2f} | {resolved}"


def main():
    if len(sys.argv) < 2:
        print("Usage: strategy_details.py <strategy_name>")
        print(f"Valid: {', '.join(VALID_STRATEGIES)}")
        print("Shortcuts: ev, fade, weather, arb, resolution, stale, corr")
        sys.exit(1)

    arg = sys.argv[1].lower().strip().lstrip("/")
    strategy = STRATEGY_ALIASES.get(arg, arg)
    if strategy not in VALID_STRATEGIES:
        print(f"Unknown strategy '{arg}'.")
        print(f"Valid: {', '.join(VALID_STRATEGIES)}")
        print("Shortcuts: ev, fade, weather, arb, resolution, stale, corr")
        sys.exit(1)

    db = open_db()
    trades = load_trades(strategy)
    meta = strategy_metadata().get(strategy, {})
    latest_run = get_latest_runs(db, n=1)
    checks = _recent_checks(db, strategy, limit=4)
    skip_reasons = _top_skip_reasons(db, strategy, limit=3)

    open_trades = [t for t in trades if t["status"] == "open"]
    closed_trades = [t for t in trades if t["status"] == "closed"]
    open_exposure = sum(float(t["amount_usdc"]) for t in open_trades)
    total_staked = sum(float(t["amount_usdc"]) for t in closed_trades)
    total_pnl = sum(float(t["pnl_usdc"]) for t in closed_trades)
    wins = sum(1 for t in closed_trades if float(t["pnl_usdc"]) > 0)
    roi = total_pnl / total_staked * 100 if total_staked else 0
    win_rate = wins / len(closed_trades) * 100 if closed_trades else 0
    lifecycle = "active" if strategy in ACTIVE_STRATEGIES else "legacy"

    lines = [f"*PPLayouts — {strategy}*\n"]
    lines.append(
        f"{meta.get('edge_type','other')}/{meta.get('time_window','?')} [{lifecycle}] | "
        f"{len(open_trades)} open (${open_exposure:.1f}) | {len(closed_trades)} closed | "
        f"{roi:+.0f}% ROI | {win_rate:.0f}% WR\n"
    )

    if latest_run:
        run = latest_run[0]
        lines.append(
            f"Latest run: {run.get('mode')} | {run.get('status')} | "
            f"{run.get('markets_fetched') or 0} mkts | +{run.get('new_positions_count') or 0} new\n"
        )

    if skip_reasons:
        lines.append("Recent skip reasons:")
        for reason in skip_reasons:
            lines.append(f"  - {reason[:64]}")
        lines.append("")

    if checks:
        lines.append("Recent checks:")
        for row in checks:
            lines.append(_format_check(strategy, row))
        lines.append("")

    if closed_trades:
        lines.append("Closed:")
        for t in closed_trades[-5:]:
            lines.append(_format_trade(t))
        lines.append("")

    if open_trades:
        lines.append(f"Open ({len(open_trades)}):")
        for t in open_trades[:8]:
            lines.append(_format_trade(t))
        if len(open_trades) > 8:
            lines.append(f"  ... and {len(open_trades) - 8} more")

    if not trades and not checks:
        lines.append("No trades or recent checks found.")

    print("\n".join(lines))


if __name__ == "__main__":
    main()

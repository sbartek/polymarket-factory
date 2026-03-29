#!/usr/bin/env python3
"""
/details <strategy>  — returns open + closed trades for a strategy from trades.csv.
Called by the ppplayouts OpenClaw skill.
Usage: uv run openclaw-skill/scripts/strategy_details.py <strategy_name>
"""
import csv
import sys
from pathlib import Path

TRADES_CSV = Path(__file__).parents[2] / "data" / "trades.csv"

STRATEGY_ALIASES = {
    "ev": "ev_news",
    "fade": "fade_certainty",
    "weather": "weather_edge",
    "arb": "spread_arb",
    "resolution": "resolution_hunter",
    "hunter": "resolution_hunter",
}

VALID_STRATEGIES = ["ev_news", "fade_certainty", "weather_edge", "spread_arb", "resolution_hunter"]


def load_trades(strategy: str) -> list[dict]:
    if not TRADES_CSV.exists():
        return []
    with open(TRADES_CSV, newline="") as f:
        return [r for r in csv.DictReader(f) if r["strategy"] == strategy]


def format_trade(t: dict) -> str:
    status = t["status"]
    outcome = t["outcome"]
    title = t["market_title"][:55]
    closes = t["closes"][:10] if t["closes"] else "?"

    if status == "open":
        mp = float(t["entry_price"]) * 100
        amount = float(t["amount_usdc"])
        return f"  OPEN  {outcome} {title}\n        ${amount:.1f} @ {mp:.0f}%  closes {closes}"
    else:
        pnl = float(t["pnl_usdc"])
        amount = float(t["amount_usdc"])
        sign = "✅" if pnl > 0 else "❌"
        resolved = t.get("resolved_outcome", "?")
        return (
            f"  {sign} {outcome} {title}\n"
            f"        ${amount:.1f} → {pnl:+.2f}  resolved: {resolved}"
        )


def main():
    if len(sys.argv) < 2:
        print("Usage: strategy_details.py <strategy_name>")
        print(f"Valid: {', '.join(VALID_STRATEGIES)}")
        print(f"Aliases: {', '.join(STRATEGY_ALIASES)}")
        sys.exit(1)

    arg = sys.argv[1].lower().strip().lstrip("/")
    strategy = STRATEGY_ALIASES.get(arg, arg)

    if strategy not in VALID_STRATEGIES:
        print(f"Unknown strategy '{arg}'.")
        print(f"Valid: {', '.join(VALID_STRATEGIES)}")
        print(f"Shortcuts: ev, fade, weather, arb, resolution")
        sys.exit(1)

    trades = load_trades(strategy)
    if not trades:
        print(f"No trades found for '{strategy}'.")
        sys.exit(0)

    open_trades = [t for t in trades if t["status"] == "open"]
    closed_trades = [t for t in trades if t["status"] == "closed"]

    total_staked = sum(float(t["amount_usdc"]) for t in closed_trades)
    total_pnl = sum(float(t["pnl_usdc"]) for t in closed_trades)
    wins = sum(1 for t in closed_trades if float(t["pnl_usdc"]) > 0)
    roi = total_pnl / total_staked * 100 if total_staked else 0
    win_rate = wins / len(closed_trades) * 100 if closed_trades else 0

    lines = [f"*PPLayouts — {strategy}*\n"]

    # Summary line
    pnl_sign = "+" if total_pnl >= 0 else ""
    lines.append(
        f"{len(open_trades)} open | {len(closed_trades)} closed | "
        f"${total_staked:.0f} staked | {pnl_sign}${total_pnl:.1f} P&L | "
        f"{roi:+.0f}% ROI | {win_rate:.0f}% WR\n"
    )

    if closed_trades:
        lines.append("*Closed:*")
        for t in closed_trades[-10:]:  # last 10
            lines.append(format_trade(t))
        lines.append("")

    if open_trades:
        lines.append(f"*Open ({len(open_trades)}):*")
        for t in open_trades[:15]:  # first 15
            lines.append(format_trade(t))
        if len(open_trades) > 15:
            lines.append(f"  ... and {len(open_trades) - 15} more")

    print("\n".join(lines))


if __name__ == "__main__":
    main()

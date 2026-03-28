"""
Weekly evaluation report — run manually to assess strategy performance.

Usage:
  uv run eval/report.py
  uv run eval/report.py --kill-threshold 0.30
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

TRADES_CSV = Path(__file__).parents[1] / "data" / "trades.csv"

KILL_WIN_RATE = 0.30     # kill if win rate < 30% (with ≥5 closed trades)
KILL_ROI = -0.10         # kill if ROI < -10%
MIN_TRADES_TO_EVALUATE = 5


def load_trades() -> list[dict]:
    if not TRADES_CSV.exists():
        return []
    with open(TRADES_CSV) as f:
        return list(csv.DictReader(f))


def evaluate():
    trades = load_trades()
    if not trades:
        print("No trades yet.")
        return

    closed = [t for t in trades if t["status"] == "closed"]
    open_ = [t for t in trades if t["status"] == "open"]

    by_strategy: dict[str, list] = defaultdict(list)
    for t in closed:
        by_strategy[t["strategy"]].append(t)

    print(f"\n{'='*60}")
    print("WEEKLY STRATEGY EVALUATION REPORT")
    print(f"{'='*60}")
    print(f"Total trades: {len(trades)} ({len(closed)} closed, {len(open_)} open)\n")

    verdicts = []

    for name, strades in sorted(by_strategy.items()):
        staked = sum(float(t["amount_usdc"]) for t in strades)
        pnl = sum(float(t["pnl_usdc"]) for t in strades)
        wins = [t for t in strades if float(t["pnl_usdc"]) > 0]
        win_rate = len(wins) / len(strades) if strades else 0
        roi = pnl / staked if staked else 0
        n = len(strades)

        print(f"  [{name}]")
        print(f"    Closed trades : {n}")
        print(f"    Win rate      : {win_rate*100:.0f}% ({len(wins)}/{n})")
        print(f"    Total staked  : ${staked:.2f}")
        print(f"    P&L           : ${pnl:+.2f}  ROI: {roi*100:+.1f}%")

        if n >= MIN_TRADES_TO_EVALUATE:
            if win_rate < KILL_WIN_RATE or roi < KILL_ROI:
                verdict = "KILL ❌"
            elif win_rate >= 0.50 and roi > 0:
                verdict = "KEEP ✅"
            else:
                verdict = "WATCH ⚠️  (more data needed)"
        else:
            verdict = f"TOO EARLY (need {MIN_TRADES_TO_EVALUATE - n} more closed trades)"

        print(f"    Verdict       : {verdict}\n")
        verdicts.append((name, verdict))

    print(f"{'─'*60}")
    print("SUMMARY:")
    for name, v in verdicts:
        print(f"  {name}: {v}")
    print()


if __name__ == "__main__":
    evaluate()

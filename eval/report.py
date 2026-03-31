"""
Weekly evaluation report — run manually to assess strategy performance.
Now also groups results by strategy time window and edge type, and splits active vs legacy.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from factory.broker import PaperBroker
from factory.strategy_meta import ACTIVE_STRATEGIES, strategy_metadata

KILL_WIN_RATE = 0.30
KILL_ROI = -0.10
MIN_TRADES_TO_EVALUATE = 5


def load_trades() -> list[dict]:
    return PaperBroker(export_csv=False).get_all_trades()


def _stats_for(trades: list[dict]) -> dict:
    staked = sum(float(t["amount_usdc"]) for t in trades)
    pnl = sum(float(t["pnl_usdc"]) for t in trades)
    wins = [t for t in trades if float(t["pnl_usdc"]) > 0]
    n = len(trades)
    return {
        "closed": n,
        "wins": len(wins),
        "win_rate": len(wins) / n if n else 0,
        "staked": staked,
        "pnl": pnl,
        "roi": pnl / staked if staked else 0,
    }


def _verdict(stats: dict) -> str:
    n = stats["closed"]
    if n >= MIN_TRADES_TO_EVALUATE:
        if stats["win_rate"] < KILL_WIN_RATE or stats["roi"] < KILL_ROI:
            return "KILL ❌"
        if stats["win_rate"] >= 0.50 and stats["roi"] > 0:
            return "KEEP ✅"
        return "WATCH ⚠️  (more data needed)"
    return f"TOO EARLY (need {MIN_TRADES_TO_EVALUATE - n} more closed trades)"


def evaluate():
    trades = load_trades()
    if not trades:
        print("No trades yet.")
        return

    meta = strategy_metadata()
    closed = [t for t in trades if t["status"] == "closed"]
    open_ = [t for t in trades if t["status"] == "open"]

    by_strategy: dict[str, list] = defaultdict(list)
    by_window: dict[str, list] = defaultdict(list)
    by_edge: dict[str, list] = defaultdict(list)
    by_lifecycle: dict[str, list] = defaultdict(list)

    for t in closed:
        strategy = t["strategy"]
        by_strategy[strategy].append(t)
        m = meta.get(strategy, {})
        by_window[m.get("time_window", "unknown")].append(t)
        by_edge[m.get("edge_type", "other")].append(t)
        by_lifecycle["active" if strategy in ACTIVE_STRATEGIES else "legacy"].append(t)

    print(f"\n{'='*60}")
    print("WEEKLY STRATEGY EVALUATION REPORT")
    print(f"{'='*60}")
    print(f"Total trades: {len(trades)} ({len(closed)} closed, {len(open_)} open)\n")

    verdicts = []
    for name, strades in sorted(by_strategy.items()):
        stats = _stats_for(strades)
        m = meta.get(name, {})
        lifecycle = "active" if name in ACTIVE_STRATEGIES else "legacy"
        print(f"  [{name}]  edge={m.get('edge_type','other')} | window={m.get('time_window','?')} | {lifecycle}")
        print(f"    Closed trades : {stats['closed']}")
        print(f"    Win rate      : {stats['win_rate']*100:.0f}% ({stats['wins']}/{stats['closed']})")
        print(f"    Total staked  : ${stats['staked']:.2f}")
        print(f"    P&L           : ${stats['pnl']:+.2f}  ROI: {stats['roi']*100:+.1f}%")
        verdict = _verdict(stats)
        print(f"    Verdict       : {verdict}\n")
        verdicts.append((name, verdict))

    print(f"{'─'*60}")
    print("ACTIVE VS LEGACY:")
    for group, gtrades in sorted(by_lifecycle.items()):
        stats = _stats_for(gtrades)
        print(f"  {group:<8} {stats['closed']:>3} closed | WR {stats['win_rate']*100:>4.0f}% | ROI {stats['roi']*100:+5.1f}% | P&L ${stats['pnl']:+.2f}")

    print(f"{'─'*60}")
    print("BY TIME WINDOW:")
    for window, wtrades in sorted(by_window.items()):
        stats = _stats_for(wtrades)
        print(f"  {window:<12} {stats['closed']:>3} closed | WR {stats['win_rate']*100:>4.0f}% | ROI {stats['roi']*100:+5.1f}% | P&L ${stats['pnl']:+.2f}")

    print(f"{'─'*60}")
    print("BY EDGE TYPE:")
    for edge, etrades in sorted(by_edge.items()):
        stats = _stats_for(etrades)
        print(f"  {edge:<16} {stats['closed']:>3} closed | WR {stats['win_rate']*100:>4.0f}% | ROI {stats['roi']*100:+5.1f}% | P&L ${stats['pnl']:+.2f}")

    print(f"{'─'*60}")
    print("SUMMARY:")
    for name, v in verdicts:
        print(f"  {name}: {v}")
    print()


if __name__ == "__main__":
    evaluate()

"""Portfolio summary — P&L and stats across all strategies."""
from .broker import PaperBroker


def summary(broker: PaperBroker) -> dict:
    trades = broker.get_all_trades()
    closed = [t for t in trades if t["status"] == "closed"]
    open_ = [t for t in trades if t["status"] == "open"]

    total_staked = sum(float(t["amount_usdc"]) for t in closed)
    total_pnl = sum(float(t["pnl_usdc"]) for t in closed)
    wins = [t for t in closed if float(t["pnl_usdc"]) > 0]
    open_exposure = sum(float(t["amount_usdc"]) for t in open_)

    by_strategy: dict[str, dict] = {}
    for t in trades:
        s = t["strategy"]
        if s not in by_strategy:
            by_strategy[s] = {"trades": 0, "closed": 0, "wins": 0, "staked": 0.0, "pnl": 0.0}
        by_strategy[s]["trades"] += 1
        if t["status"] == "closed":
            by_strategy[s]["closed"] += 1
            by_strategy[s]["staked"] += float(t["amount_usdc"])
            by_strategy[s]["pnl"] += float(t["pnl_usdc"])
            if float(t["pnl_usdc"]) > 0:
                by_strategy[s]["wins"] += 1

    return {
        "total_trades": len(trades),
        "closed": len(closed),
        "open": len(open_),
        "open_exposure_usdc": round(open_exposure, 2),
        "total_staked": round(total_staked, 2),
        "total_pnl": round(total_pnl, 4),
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "roi": round(total_pnl / total_staked, 3) if total_staked else None,
        "by_strategy": by_strategy,
    }


def format_summary(stats: dict) -> str:
    lines = ["*Portfolio summary*\n"]
    lines.append(
        f"Open: {stats['open']} positions (${stats['open_exposure_usdc']} exposed)\n"
        f"Closed: {stats['closed']} trades | Staked: ${stats['total_staked']}\n"
        f"P&L: ${stats['total_pnl']:+.2f} | ROI: {(stats['roi'] or 0)*100:+.1f}% | "
        f"Win rate: {(stats['win_rate'] or 0)*100:.0f}%\n"
    )
    for name, s in stats["by_strategy"].items():
        roi = s["pnl"] / s["staked"] * 100 if s["staked"] else 0
        wr = s["wins"] / s["closed"] * 100 if s["closed"] else 0
        lines.append(
            f"  [{name}] {s['closed']} closed | P&L ${s['pnl']:+.2f} | "
            f"ROI {roi:+.1f}% | WR {wr:.0f}%"
        )
    return "\n".join(lines)


def format_wa_table(stats: dict, new_by_strategy: dict[str, int]) -> str:
    """
    Mobile-friendly per-strategy lines for WhatsApp.
    new_by_strategy: {strategy_name: count_of_new_positions_this_run}
    Staked/P&L/ROI only shown for strategies with at least one closed trade.
    """
    lines = []
    for name, s in stats["by_strategy"].items():
        new = new_by_strategy.get(name, 0)
        new_str = f"+{new}" if new else "0"

        if s["staked"] > 0:
            roi = s["pnl"] / s["staked"] * 100
            pnl_sign = "+" if s["pnl"] >= 0 else "-"
            perf = f" · ${s['staked']:.0f} → {pnl_sign}${abs(s['pnl']):.1f} ({roi:+.0f}%)"
        else:
            perf = ""

        lines.append(f"*{name}:* {new_str} new · {s['closed']} cls{perf}")

    total_roi = stats["roi"] or 0
    total_pnl_sign = "+" if stats["total_pnl"] >= 0 else "-"
    total_line = (
        f"*Total: {stats['open']} open · "
        f"${stats['total_staked']} staked · "
        f"{total_pnl_sign}${abs(stats['total_pnl']):.1f} P&L · "
        f"{total_roi*100:+.0f}% ROI*"
    )
    return "\n".join(lines) + "\n\n" + total_line

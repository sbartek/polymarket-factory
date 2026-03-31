"""Portfolio summary — P&L and stats across all strategies."""
from .broker import PaperBroker
from .strategy_meta import ACTIVE_STRATEGIES, TIME_WINDOW_EXPOSURE_CAPS, strategy_metadata


def summary(broker: PaperBroker) -> dict:
    trades = broker.get_all_trades()
    closed = [t for t in trades if t["status"] == "closed"]
    open_ = [t for t in trades if t["status"] == "open"]
    meta = strategy_metadata()

    total_staked = sum(float(t["amount_usdc"]) for t in closed)
    total_pnl = sum(float(t["pnl_usdc"]) for t in closed)
    wins = [t for t in closed if float(t["pnl_usdc"]) > 0]
    open_exposure = sum(float(t["amount_usdc"]) for t in open_)

    by_strategy: dict[str, dict] = {}
    by_time_window: dict[str, dict] = {}
    by_edge_type: dict[str, dict] = {}
    by_status_group: dict[str, dict] = {}

    def ensure(bucket: dict[str, dict], key: str):
        if key not in bucket:
            bucket[key] = {
                "trades": 0, "open": 0, "closed": 0, "wins": 0,
                "staked": 0.0, "pnl": 0.0, "open_exposure": 0.0,
            }

    for t in trades:
        s = t["strategy"]
        m = meta.get(s, {})
        tw = m.get("time_window", "unknown")
        edge = m.get("edge_type", "other")
        status_group = "active" if s in ACTIVE_STRATEGIES else "legacy"

        ensure(by_strategy, s)
        ensure(by_time_window, tw)
        ensure(by_edge_type, edge)
        ensure(by_status_group, status_group)

        for bucket, key in (
            (by_strategy, s),
            (by_time_window, tw),
            (by_edge_type, edge),
            (by_status_group, status_group),
        ):
            bucket[key]["trades"] += 1
            if t["status"] == "open":
                bucket[key]["open"] += 1
                bucket[key]["open_exposure"] += float(t["amount_usdc"])
            else:
                bucket[key]["closed"] += 1
                bucket[key]["staked"] += float(t["amount_usdc"])
                bucket[key]["pnl"] += float(t["pnl_usdc"])
                if float(t["pnl_usdc"]) > 0:
                    bucket[key]["wins"] += 1

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
        "by_time_window": by_time_window,
        "by_edge_type": by_edge_type,
        "by_status_group": by_status_group,
        "meta": meta,
        "window_caps": {k: v for k, v in ((w, TIME_WINDOW_EXPOSURE_CAPS.get(w)) for w in by_time_window.keys() | set(TIME_WINDOW_EXPOSURE_CAPS.keys()))},
    }


def _format_bucket_line(name: str, s: dict) -> str:
    roi = s["pnl"] / s["staked"] * 100 if s["staked"] else 0
    wr = s["wins"] / s["closed"] * 100 if s["closed"] else 0
    return (
        f"  [{name}] {s['open']} open | {s['closed']} closed | "
        f"exp ${s['open_exposure']:.1f} | P&L ${s['pnl']:+.2f} | "
        f"ROI {roi:+.1f}% | WR {wr:.0f}%"
    )


def format_summary(stats: dict) -> str:
    lines = ["*Portfolio summary*\n"]
    lines.append(
        f"Open: {stats['open']} positions (${stats['open_exposure_usdc']} exposed)\n"
        f"Closed: {stats['closed']} trades | Staked: ${stats['total_staked']}\n"
        f"P&L: ${stats['total_pnl']:+.2f} | ROI: {(stats['roi'] or 0)*100:+.1f}% | "
        f"Win rate: {(stats['win_rate'] or 0)*100:.0f}%\n"
    )

    lines.append("*Active vs legacy*")
    for name, s in stats["by_status_group"].items():
        lines.append(_format_bucket_line(name, s))

    lines.append("\n*By strategy*")
    for name, s in stats["by_strategy"].items():
        meta = stats["meta"].get(name, {})
        lifecycle = "active" if name in ACTIVE_STRATEGIES else "legacy"
        lines.append(
            _format_bucket_line(name, s)
            + f" | {meta.get('edge_type','other')} | {meta.get('time_window','?')} | {lifecycle}"
        )

    lines.append("\n*By time window*")
    for name, s in stats["by_time_window"].items():
        cap = stats.get("window_caps", {}).get(name)
        cap_str = f" | cap ${cap:.0f}" if cap is not None else ""
        lines.append(_format_bucket_line(name, s) + cap_str)

    lines.append("\n*By edge type*")
    for name, s in stats["by_edge_type"].items():
        lines.append(_format_bucket_line(name, s))
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
        meta = stats["meta"].get(name, {})

        if s["staked"] > 0:
            roi = s["pnl"] / s["staked"] * 100
            pnl_sign = "+" if s["pnl"] >= 0 else "-"
            perf = f" · ${s['staked']:.0f} → {pnl_sign}${abs(s['pnl']):.1f} ({roi:+.0f}%)"
        else:
            perf = ""

        lifecycle = "A" if name in ACTIVE_STRATEGIES else "L"
        lines.append(
            f"*{name}:* {new_str} new · {s['closed']} cls · "
            f"{meta.get('edge_type','other')}/{meta.get('time_window','?')}[{lifecycle}]{perf}"
        )

    active = stats["by_status_group"].get("active", {"open": 0, "open_exposure": 0.0, "staked": 0.0, "pnl": 0.0})
    legacy = stats["by_status_group"].get("legacy", {"open": 0, "open_exposure": 0.0, "staked": 0.0, "pnl": 0.0})
    total_roi = stats["roi"] or 0
    total_pnl_sign = "+" if stats["total_pnl"] >= 0 else "-"
    total_line = (
        f"*Total: {stats['open']} open · "
        f"${stats['total_staked']} staked · "
        f"{total_pnl_sign}${abs(stats['total_pnl']):.1f} P&L · "
        f"{total_roi*100:+.0f}% ROI*"
    )
    split_line = (
        f"*Active vs legacy:* A {active['open']} open (${active['open_exposure']:.0f}) · "
        f"L {legacy['open']} open (${legacy['open_exposure']:.0f})"
    )
    return "\n".join(lines) + "\n\n" + total_line + "\n" + split_line

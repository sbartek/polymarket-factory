"""Daily 24h review briefing — DB-query-only, no market fetching or LLM calls."""
from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta

from .db import FactoryDB, utcnow
from .notify import send_notification
from .strategy_meta import ACTIVE_STRATEGIES, STRATEGY_EXPOSURE_CAPS, TIME_WINDOW_EXPOSURE_CAPS, strategy_metadata


def _cutoff_24h() -> str:
    return (datetime.now(UTC) - timedelta(hours=24)).isoformat(timespec="seconds")


def _cutoff_7d() -> str:
    return (datetime.now(UTC) - timedelta(days=7)).isoformat(timespec="seconds")


def portfolio_24h(db: FactoryDB) -> dict:
    """Trades opened/closed in last 24h, plus snapshot delta."""
    cutoff = _cutoff_24h()
    with db._conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS cnt, COALESCE(SUM(amount_usdc), 0) AS staked FROM trades WHERE opened_at >= %s", (cutoff,))
        opened = dict(cur.fetchone())
        cur.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(pnl_usdc), 0) AS pnl FROM trades WHERE closed_at >= %s AND status = 'closed'",
            (cutoff,),
        )
        closed = dict(cur.fetchone())
        cur.execute("SELECT COUNT(*) AS cnt, COALESCE(SUM(amount_usdc), 0) AS exposure FROM trades WHERE status = 'open'")
        open_pos = dict(cur.fetchone())

    now_ts = datetime.now(UTC).isoformat(timespec="seconds")
    snap_now = db.get_latest_portfolio_snapshot_before(now_ts)
    snap_24h = db.get_latest_portfolio_snapshot_before(cutoff)
    unrealized_now = float(snap_now.get("unrealized_pnl_usdc") or 0) if snap_now else 0
    unrealized_24h = float(snap_24h.get("unrealized_pnl_usdc") or 0) if snap_24h else 0

    return {
        "opened_count": int(opened["cnt"]),
        "opened_staked": round(float(opened["staked"]), 2),
        "closed_count": int(closed["cnt"]),
        "closed_pnl": round(float(closed["pnl"]), 2),
        "open_count": int(open_pos["cnt"]),
        "open_exposure": round(float(open_pos["exposure"]), 2),
        "unrealized_now": round(unrealized_now, 2),
        "unrealized_24h": round(unrealized_24h, 2),
        "unrealized_delta": round(unrealized_now - unrealized_24h, 2),
    }


def expiring_soon(db: FactoryDB) -> list[dict]:
    """Open positions with markets closing in the next 48h."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    cutoff_48h = (datetime.now(UTC) + timedelta(hours=48)).isoformat(timespec="seconds")
    with db._conn() as (conn, cur):
        cur.execute(
            """SELECT strategy, market_title, closes, amount_usdc, outcome
               FROM trades
               WHERE status = 'open' AND closes != '' AND closes >= %s AND closes <= %s
               ORDER BY closes ASC
               LIMIT 10""",
            (now, cutoff_48h),
        )
        return [dict(r) for r in cur.fetchall()]


def strategy_health_7d(db: FactoryDB) -> list[dict]:
    """Per-strategy win/loss/P&L over the last 7 days."""
    cutoff = _cutoff_7d()
    with db._conn() as (conn, cur):
        cur.execute(
            """SELECT strategy,
                      COUNT(*) AS total,
                      SUM(CASE WHEN pnl_usdc > 0 THEN 1 ELSE 0 END) AS wins,
                      ROUND(CAST(SUM(pnl_usdc) AS NUMERIC), 2) AS pnl
               FROM trades
               WHERE closed_at >= %s AND status = 'closed'
               GROUP BY strategy
               ORDER BY pnl DESC""",
            (cutoff,),
        )
        return [dict(r) for r in cur.fetchall()]


def exposure_vs_caps(db: FactoryDB) -> dict:
    """Current exposure by strategy and mode, compared to caps."""
    meta = strategy_metadata()
    with db._conn() as (conn, cur):
        cur.execute(
            """SELECT strategy, COALESCE(NULLIF(mode, ''), 'paper') AS mode, SUM(amount_usdc) AS exposure
               FROM trades WHERE status = 'open'
               GROUP BY strategy, COALESCE(NULLIF(mode, ''), 'paper')
               ORDER BY exposure DESC"""
        )
        rows = [dict(r) for r in cur.fetchall()]

    paper_total = sum(float(r["exposure"]) for r in rows if r["mode"] == "paper")
    live_total = sum(float(r["exposure"]) for r in rows if r["mode"] == "live")

    near_cap = []
    for r in rows:
        cap = STRATEGY_EXPOSURE_CAPS.get(r["strategy"], 50.0)
        exposure = round(float(r["exposure"]), 2)
        if cap > 0 and exposure >= cap * 0.7:
            near_cap.append({
                "strategy": r["strategy"],
                "mode": r["mode"],
                "exposure": exposure,
                "cap": cap,
            })

    return {
        "paper_total": round(paper_total, 2),
        "live_total": round(live_total, 2),
        "near_cap": near_cap,
    }


def watch_list(db: FactoryDB) -> list[dict]:
    """High-EV signals from last 24h that were blocked (cap, cooldown, exposure)."""
    cutoff = _cutoff_24h()
    with db._conn() as (conn, cur):
        cur.execute(
            """SELECT d.strategy, d.reason, s.market_title, s.ev_pp, s.outcome
               FROM decisions d
               JOIN signals s ON d.run_id = s.run_id AND d.strategy = s.strategy AND d.market_id = s.market_id
               WHERE d.created_at >= %s
                 AND d.decision IN ('skip', 'alert')
                 AND (d.reason LIKE '%%cap%%' OR d.reason LIKE '%%cooldown%%' OR d.reason LIKE '%%exposure%%' OR d.reason LIKE '%%duplicate%%')
                 AND s.ev_pp > 5
               ORDER BY s.ev_pp DESC
               LIMIT 5""",
            (cutoff,),
        )
        return [dict(r) for r in cur.fetchall()]


def format_review(portfolio: dict, expiring: list[dict], health: list[dict], loss_streaks: dict,
                  exposure: dict, watches: list[dict]) -> str:
    """Format the 24h review as a WhatsApp-friendly message."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"*24h Review — {now}*\n"]

    # Portfolio 24h
    lines.append("*Portfolio 24h:*")
    lines.append(f"Opened: {portfolio['opened_count']} (${portfolio['opened_staked']:.2f}) | Closed: {portfolio['closed_count']} | P&L: ${portfolio['closed_pnl']:+.2f}")
    lines.append(f"Unrealized: ${portfolio['unrealized_24h']:.2f} → ${portfolio['unrealized_now']:.2f} (${portfolio['unrealized_delta']:+.2f})")
    lines.append(f"Open: {portfolio['open_count']} pos (${portfolio['open_exposure']:.2f} exposed)")

    # Expiring soon
    if expiring:
        lines.append("")
        lines.append(f"*Expiring 48h:* {len(expiring)}")
        for e in expiring[:5]:
            closes_short = e["closes"][:10] if e.get("closes") else "?"
            lines.append(f"- [{e['strategy']}] {e['market_title'][:50]} | {closes_short} | ${float(e['amount_usdc']):.2f}")

    # Strategy 7d health
    if health:
        lines.append("")
        lines.append("*Strategy 7d:*")
        for h in health[:8]:
            total = int(h["total"])
            wins = int(h["wins"])
            pnl = float(h["pnl"])
            wr = round(wins / total * 100) if total else 0
            lines.append(f"{h['strategy']}: {wins}W/{total - wins}L ${pnl:+.2f} {wr}%")

    # Loss streaks
    if loss_streaks:
        lines.append("")
        for strat, info in loss_streaks.items():
            lines.append(f"!! {strat}: {info['streak']} consecutive losses (${info['total_lost']:.2f})")

    # Exposure
    lines.append("")
    lines.append(f"*Exposure:* Paper ${exposure['paper_total']:.2f} | Live ${exposure['live_total']:.2f}")
    if exposure["near_cap"]:
        near = " | ".join(f"{nc['strategy']} ${nc['exposure']:.0f}/${nc['cap']:.0f}" for nc in exposure["near_cap"][:4])
        lines.append(f"Near cap: {near}")

    # Watch list
    if watches:
        lines.append("")
        lines.append(f"*Watch list:* {len(watches)}")
        for w in watches:
            reason_short = w["reason"].split(":")[-1].strip() if ":" in w["reason"] else w["reason"]
            lines.append(f"- [{w['strategy']}] {w['outcome']} {w['market_title'][:45]} | {float(w['ev_pp']):+.0f}pp | {reason_short}")

    return "\n".join(lines)


def run_review(send: bool = True) -> str:
    """Run the 24h review briefing. Returns the formatted message."""
    db = FactoryDB()
    run_id = db.start_run(mode="review")

    try:
        portfolio = portfolio_24h(db)
        expiring = expiring_soon(db)
        health = strategy_health_7d(db)
        loss_streaks = db.get_loss_streaks(min_streak=5)
        loss_streaks = {s: info for s, info in loss_streaks.items() if s in ACTIVE_STRATEGIES}
        exposure = exposure_vs_caps(db)
        watches = watch_list(db)

        msg = format_review(portfolio, expiring, health, loss_streaks, exposure, watches)

        if send:
            report = send_notification(msg)
            sent = bool(report.get("any_sent"))
            print(f"Notification {'sent' if sent else 'FAILED'}")
        else:
            print("--- REVIEW PREVIEW ---")
            print(msg)
            print("--- END PREVIEW ---")

        db.finish_run(run_id, status="completed")
        return msg
    except Exception as e:
        db.finish_run(run_id, status="failed", notes=str(e)[:200])
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="24h review briefing")
    parser.add_argument("--no-send", action="store_true", help="Preview only, don't send notification")
    args = parser.parse_args()
    run_review(send=not args.no_send)

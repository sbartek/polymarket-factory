"""Live order executor — runs on Mac (non-US region) to place CLOB orders.

Reads pending orders from live_order_queue, executes via Polymarket CLOB API,
records trades in the trades table, and updates queue status.

Usage:
    python -m factory.live_executor          # process pending orders
    python -m factory.live_executor --dry    # show what would execute
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, UTC

from .clob import place_market_order
from .db import FactoryDB, TRADE_FIELDS
from .live_broker import LIVE_EXPOSURE_CAP_USDC
from .models import Trade
from .notify import send_notification
from .strategy_meta import ACTIVE_STRATEGIES, strategy_metadata


def _live_exposure(db: FactoryDB) -> float:
    return sum(
        float(t.get("amount_usdc") or 0)
        for t in db.load_trades(mode="live")
        if t.get("status") == "open" and t.get("mode") == "live"
    )


def _pending_exposure(db: FactoryDB) -> float:
    """Sum of amounts in pending queue (not yet executed)."""
    orders = db.get_pending_live_orders()
    return sum(float(o.get("amount_usdc") or 0) for o in orders)


def execute_pending_orders(db: FactoryDB, dry_run: bool = False) -> int:
    orders = db.get_pending_live_orders()
    if not orders:
        print("[live_executor] no pending orders")
        return 0

    current_exposure = _live_exposure(db)
    print(f"[live_executor] {len(orders)} pending orders, current live exposure: ${current_exposure:.2f}")

    meta = strategy_metadata()
    executed = 0

    for order in orders:
        oid = order["id"]
        strategy = order["strategy"]
        amount = float(order["amount_usdc"])
        token_id = order["token_id"]
        outcome = order["outcome"]
        title = (order.get("market_title") or "?")[:60]

        # Check exposure cap
        if current_exposure + amount > LIVE_EXPOSURE_CAP_USDC:
            print(f"  [{strategy}] SKIP {title} | exposure cap (${current_exposure:.0f} + ${amount:.0f} > ${LIVE_EXPOSURE_CAP_USDC:.0f})")
            db.update_live_order(oid, "skipped", error="exposure_cap")
            continue

        # Check duplicate (already have open position for this market)
        if db.has_open_position(order["market_id"], strategy, mode="live"):
            print(f"  [{strategy}] SKIP {title} | already have live position")
            db.update_live_order(oid, "skipped", error="duplicate")
            continue

        if dry_run:
            print(f"  [{strategy}] DRY {outcome} {title} | ${amount} | token={token_id[:20]}...")
            continue

        # Place the order
        market_price = float(order.get("market_price") or 0.5)
        price = market_price if outcome == "YES" else (1.0 - market_price)
        size = round(amount / max(price, 0.01), 4)

        try:
            resp = place_market_order(token_id, size)
            clob_order_id = resp.get("orderID", "?")
            print(f"  [{strategy}] EXECUTED {outcome} {title} | ${amount} | order={clob_order_id}")

            # Record trade
            trade_id = str(uuid.uuid4())[:8]
            meta_item = meta.get(strategy, {})
            trade_record = {
                "id": trade_id,
                "strategy": strategy,
                "market_id": order["market_id"],
                "market_title": order.get("market_title", ""),
                "outcome": outcome,
                "amount_usdc": round(amount, 2),
                "entry_price": round(price, 4),
                "shares": round(size, 4),
                "opened_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "closes": order.get("closes", ""),
                "url": order.get("url", ""),
                "status": "open",
                "exit_price": 0,
                "closed_at": "",
                "pnl_usdc": 0,
                "resolved_outcome": "",
                "notes": f"clob_id={clob_order_id}",
                "run_id_opened": order.get("run_id", ""),
                "run_id_closed": "",
                "lifecycle_group": "active" if strategy in ACTIVE_STRATEGIES else "legacy",
                "time_window": meta_item.get("time_window"),
                "edge_type": meta_item.get("edge_type"),
                "mode": "live",
            }
            db.insert_trade(trade_record)
            db.update_live_order(oid, "executed", trade_id=trade_id)
            current_exposure += amount
            executed += 1

            send_notification(
                f"*LIVE TRADE* [{strategy}] {outcome} {title}\n"
                f"${amount:.2f} @ {price:.3f} | order={clob_order_id}"
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            print(f"  [{strategy}] FAILED {title} | {error_msg}")
            db.update_live_order(oid, "failed", error=error_msg[:500])

    return executed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Execute pending live orders via CLOB")
    parser.add_argument("--dry", action="store_true", help="Dry run — show but don't execute")
    args = parser.parse_args()

    db = FactoryDB()
    count = execute_pending_orders(db, dry_run=args.dry)
    print(f"\n[live_executor] {'would execute' if args.dry else 'executed'} {count} orders")

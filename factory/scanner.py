"""
Phase 1 scanner — fetch markets (paginated), run all strategies, cache signals to DB.

Run independently: `python -m factory.scanner [--limit 200] [--env paper]`
Designed to run ~30min before the execute phase so that slow LLM/news calls
don't block position execution.
"""
import argparse
import os
from datetime import datetime

from .claude import reset_circuit_breaker
from .db import FactoryDB
from .feed import fetch_top_paginated
from .runner import _extract_market_observations, _log_strategy_details, _signal_to_dict
from .execution import build_market_index, snapshot_for_signal
from .strategies import STRATEGIES
from .strategy_meta import strategy_metadata, should_run_in_cycle


def scan(environment: str = "paper", market_limit: int = 200):
    """Phase 1: fetch markets, run strategies, cache signals to DB."""
    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M")
    mode = f"{environment}_scan"

    print(f"\n{'='*60}")
    print(f"POLYMARKET SCANNER (Phase 1) — {now} [{environment.upper()}]")
    print(f"{'='*60}\n")

    reset_circuit_breaker()
    db = FactoryDB()
    run_id = db.start_run(mode=mode)
    db.log_event(run_id, "info", "scan_started", payload={"mode": mode, "market_limit": market_limit})

    lock_name = f"{environment}_scanner"
    lock_acquired = db.acquire_run_lock(lock_name, run_id)
    if not lock_acquired:
        msg = f"another scan already holds the {lock_name} lock"
        print(f"Abort: {msg}")
        db.log_decision(run_id, "run_lock", "skip", reason=msg)
        db.finish_run(run_id, status="aborted", notes=msg)
        return

    meta = strategy_metadata()
    markets_fetched = 0
    total_signals = 0

    try:
        print(f"Fetching up to {market_limit} markets (paginated)...", end=" ", flush=True)
        try:
            markets = fetch_top_paginated(total=market_limit)
        except Exception as e:
            print(f"FAILED: {e}")
            db.log_event(run_id, "error", f"fetch_top_paginated failed: {e}")
            db.finish_run(run_id, status="failed", markets_fetched=0, notes=f"fetch failed: {e}")
            return
        markets_fetched = len(markets)
        print(f"{markets_fetched} markets.\n")
        db.log_event(run_id, "info", "markets_fetched", payload={"count": markets_fetched})
        db.log_market_snapshot_archive(run_id, markets, source="fetch_top_paginated")
        db.log_market_observations(run_id, _extract_market_observations(markets))

        market_index = build_market_index(markets)

        for strategy in STRATEGIES:
            strategy_meta = meta.get(strategy.name, {})
            if strategy_meta.get("paused") or getattr(strategy, "paused", False):
                print(f"Skipping [{strategy.name}] (paused).")
                db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="paused")
                continue
            if not should_run_in_cycle(strategy_meta.get("time_window", "unknown"), now_dt.hour):
                print(f"Skipping [{strategy.name}] this cycle ({strategy_meta.get('time_window')}).")
                db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="cadence",
                                details={"time_window": strategy_meta.get("time_window"), "hour": now_dt.hour})
                continue

            print(f"Scanning [{strategy.name}] ({strategy_meta.get('edge_type','other')}/{strategy_meta.get('time_window','?')})...")
            db.log_event(run_id, "info", "strategy_started", strategy=strategy.name)
            try:
                signals = strategy.scan(markets)
            except Exception as e:
                print(f"  Error in {strategy.name}.scan(): {e}")
                db.log_event(run_id, "error", f"strategy scan error: {e}", strategy=strategy.name)
                db.log_decision(run_id, "strategy_scan", "error", strategy=strategy.name, reason=str(e))
                continue

            for sig in signals:
                sig_dict = _signal_to_dict(sig)
                db.log_signal(run_id, strategy.name, sig_dict,
                              time_window=strategy_meta.get("time_window"),
                              edge_type=strategy_meta.get("edge_type"),
                              decision_status="generated",
                              phase="scan")
                execution_snapshot = snapshot_for_signal(sig, strategy, market_index)
                db.log_signal_execution_check(run_id, execution_snapshot.as_dict())
                total_signals += 1
                print(f"  [{strategy.name}] {sig.outcome} {sig.market_title[:50]} | EV {sig.ev_pp:+.0f}pp | {sig.confidence}")

            print()
            _log_strategy_details(db, run_id, strategy)
            db.log_event(run_id, "info", "strategy_finished", strategy=strategy.name,
                         payload={"signals": len(signals)})

        print(f"Scan complete: {total_signals} signals cached from {markets_fetched} markets.")
        db.finish_run(run_id, status="success", markets_fetched=markets_fetched,
                      new_positions_count=0, notes=f"scan_phase: {total_signals} signals cached")
    except Exception as e:
        db.log_event(run_id, "error", f"scan_failed: {e}")
        db.finish_run(run_id, status="failed", markets_fetched=markets_fetched, notes=str(e))
        raise
    finally:
        db.release_run_lock(lock_name, run_id)

    print(f"\n{'='*60}\n")
    return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 1: scan markets and cache signals")
    parser.add_argument("--env", default=os.environ.get("FACTORY_ENV", "paper"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    scan(environment=args.env, market_limit=args.limit)

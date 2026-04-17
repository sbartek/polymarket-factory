"""
Main runner for combined/manual execution and execute-only runs.

Supports two modes:
  phase="combined" (default): fetch → scan → execute → notify (legacy single-pass)
  phase="execute": read cached signals from DB → execute → notify (fast, no LLM calls)

Use factory.scanner for the scan-only phase that caches signals.

Supports `dry_run=True` for a safe manual pass with no writes and no sends.
Supports `fast_dry_run=True` to aggressively trim slow strategy work for debugging.
Includes live-run locking + strategy detail logging.
"""
import argparse
import os
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta

from .broker import PaperBroker
from .claude import reset_circuit_breaker
from .db import FactoryDB
from .environment import classify_strategy_execution, get_environment_policy
from .live_broker import LiveBroker
from .execution import build_market_index, snapshot_for_signal
from .feed import fetch_top, fetch_top_paginated, fetch_by_slug, fetch_closed, get_market_winner, get_submarket_outcome
from .models import Signal
from .notify import send_notification, send_whatsapp
from .portfolio import summary, format_summary, format_wa_table, snapshot_open_positions
from .strategies import STRATEGIES
from .strategy_meta import ACTIVE_STRATEGIES, strategy_metadata, should_run_in_cycle


SIGNAL_PRICE_DRIFT_THRESHOLD = 0.10


class DryRunBroker:
    """Read-only wrapper around a broker-like object for safe manual passes."""

    def __init__(self, base):
        self.base = base
        self.simulated_new_positions: list[dict] = []
        self.simulated_closures: list[tuple[dict, str]] = []

    def has_position(self, market_id: str, strategy: str) -> bool:
        if self.base.has_position(market_id, strategy):
            return True
        return any(t["market_id"] == market_id and t["strategy"] == strategy for t in self.simulated_new_positions)

    def get_open_positions(self) -> list[dict]:
        real_open = self.base.get_open_positions()
        closed_ids = {t["id"] for t, _ in self.simulated_closures}
        filtered = [t for t in real_open if t["id"] not in closed_ids]
        return filtered + list(self.simulated_new_positions)

    def get_all_trades(self) -> list[dict]:
        trades = self.base.get_all_trades()
        closed_ids = {t["id"] for t, _ in self.simulated_closures}
        out = []
        for t in trades:
            if t["id"] in closed_ids:
                winner = next(w for tt, w in self.simulated_closures if tt["id"] == t["id"])
                tt = dict(t)
                tt["status"] = "closed"
                tt["resolved_outcome"] = winner
                out.append(tt)
            else:
                out.append(t)
        return out + list(self.simulated_new_positions)

    def open_position(self, signal: Signal, amount_usdc: float):
        self.simulated_new_positions.append({
            "id": f"dry-{len(self.simulated_new_positions)+1}",
            "strategy": signal.strategy,
            "market_id": signal.market_id,
            "market_title": signal.market_title,
            "outcome": signal.outcome,
            "amount_usdc": round(amount_usdc, 2),
            "entry_price": round(signal.market_price, 4),
            "shares": round(amount_usdc / max(signal.market_price, 0.01), 4),
            "opened_at": datetime.now().isoformat(timespec="seconds"),
            "closes": signal.closes,
            "url": signal.url,
            "status": "open",
            "exit_price": 0.0,
            "closed_at": "",
            "pnl_usdc": 0.0,
            "resolved_outcome": "",
            "notes": "DRY_RUN",
        })
        return self.simulated_new_positions[-1]

    def close_position(self, trade_id: str, resolved_outcome: str):
        for t in self.base.get_open_positions():
            if t["id"] == trade_id:
                self.simulated_closures.append((t, resolved_outcome))
                return


class ResearchBroker:
    """No-position broker used by the research environment."""

    def has_position(self, market_id: str, strategy: str) -> bool:
        return False

    def get_open_positions(self) -> list[dict]:
        return []

    def get_all_trades(self) -> list[dict]:
        return []

    def open_position(self, signal: Signal, amount_usdc: float):
        return None

    def close_position(self, trade_id: str, resolved_outcome: str):
        return None


def _signal_to_dict(signal: Signal) -> dict:
    return asdict(signal) if is_dataclass(signal) else dict(signal)


def _log_strategy_details(db: FactoryDB, run_id: str, strategy):
    if strategy.name == "spread_arb":
        for row in getattr(strategy, "last_basket_details", []):
            db.log_spread_arb_basket(run_id, row)
    elif strategy.name == "stale_market":
        for row in getattr(strategy, "last_check_details", []):
            db.log_stale_market_check(run_id, row)
    elif strategy.name == "correlated_pairs":
        for row in getattr(strategy, "last_check_details", []):
            db.log_correlated_pairs_check(run_id, row)
    elif strategy.name == "correlated_laggard":
        for row in getattr(strategy, "last_check_details", []):
            db.log_correlated_laggard_check(run_id, row)
    elif strategy.name == "esport48":
        for row in getattr(strategy, "last_check_details", []):
            db.log_esport48_check(run_id, row)
    elif strategy.name == "celebrity_tabloid":
        for row in getattr(strategy, "last_check_details", []):
            db.log_celebrity_tabloid_check(run_id, row)
    elif strategy.name == "polling_vs_market":
        for row in getattr(strategy, "last_check_details", []):
            db.log_polling_vs_market_check(run_id, row)
    elif strategy.name == "mutually_exclusive_oversum":
        for row in getattr(strategy, "last_check_details", []):
            db.log_mutually_exclusive_oversum_check(run_id, row)
    elif strategy.name in ("fade_certainty_v2", "resolution_hunter_v2", "weather_edge_v2"):
        details = getattr(strategy, "last_check_details", [])
        if details:
            db.log_event(run_id, "info", f"{strategy.name}_checks", strategy=strategy.name, payload={"checks": details})


def _find_event_slug_for_numeric_id(numeric_id: str, all_positions: list[dict]) -> str | None:
    """Find the event slug for a bare numeric market_id by checking sibling trades."""
    for t in all_positions:
        mid = t.get("market_id", "")
        if ":" in mid and mid.endswith(f":{numeric_id}"):
            return mid.split(":")[0]
    return None


def resolve_open_positions(broker, dry_run: bool = False, db: FactoryDB | None = None, run_id: str | None = None):
    open_positions = broker.get_open_positions()
    closed_count = 0
    closed_trades: list[dict] = []
    for t in open_positions:
        market_id = t["market_id"]
        if not market_id or str(t.get("id", "")).startswith("dry-"):
            continue
        if ":" in market_id:
            event_slug, submarket_id = market_id.split(":", 1)
        else:
            # Bare numeric ID — try to find the event slug from sibling trades
            sibling_slug = _find_event_slug_for_numeric_id(market_id, open_positions)
            if sibling_slug:
                event_slug, submarket_id = sibling_slug, market_id
            else:
                event_slug, submarket_id = market_id, None
        try:
            events = fetch_closed(event_slug)
            if not events:
                # Fallback: try fetch_by_slug (includes active events that may have resolved submarkets)
                events = fetch_by_slug(event_slug)
            if not events:
                continue
            ev = events[0]
            winner = get_submarket_outcome(ev, submarket_id) if submarket_id else get_market_winner(ev)
            if winner:
                broker.close_position(t["id"], winner)
                closed_count += 1
                closed_trades.append({
                    "strategy": t.get("strategy"),
                    "market_title": t.get("market_title"),
                    "outcome": t.get("outcome"),
                    "winner": winner,
                    "amount_usdc": float(t.get("amount_usdc") or 0.0),
                })
                print(f"  {'DRY CLOSE' if dry_run else 'Closed'} [{t['strategy']}] {t['market_title'][:50]} → {winner}")
                if db and run_id:
                    db.log_decision(run_id, "resolution", "dry_close" if dry_run else "close", strategy=t.get("strategy"), market_id=t.get("market_id"), reason="market_resolved", details={"winner": winner, "trade_id": t.get("id")})
        except Exception as e:
            print(f"  Error resolving {market_id}: {e}")
            if db and run_id:
                db.log_event(run_id, "error", f"resolve_open_positions error: {e}", strategy=t.get("strategy"), payload={"market_id": market_id})
    return closed_count, closed_trades


def _current_exposure_by_strategy_and_window(broker, meta: dict) -> tuple[dict[str, float], dict[str, float]]:
    by_strategy, by_window = {}, {}
    for t in broker.get_open_positions():
        strategy = t["strategy"]
        amount = float(t["amount_usdc"])
        by_strategy[strategy] = by_strategy.get(strategy, 0.0) + amount
        window = meta.get(strategy, {}).get("time_window", "unknown")
        by_window[window] = by_window.get(window, 0.0) + amount
    return by_strategy, by_window


def _can_open(amount: float, strategy_name: str, meta: dict, exposure_by_strategy: dict, exposure_by_window: dict) -> tuple[bool, str]:
    strategy_meta = meta.get(strategy_name, {})
    window = strategy_meta.get("time_window", "unknown")
    strategy_cap = strategy_meta.get("strategy_exposure_cap")
    window_cap = strategy_meta.get("window_exposure_cap")
    current_strategy = exposure_by_strategy.get(strategy_name, 0.0)
    current_window = exposure_by_window.get(window, 0.0)
    if strategy_cap is not None and current_strategy + amount > strategy_cap:
        return False, f"strategy cap ${strategy_cap:.0f} hit ({current_strategy:.1f} open)"
    if window_cap is not None and current_window + amount > window_cap:
        return False, f"{window} window cap ${window_cap:.0f} hit ({current_window:.1f} open)"
    return True, ""


@dataclass
class _ExecuteResult:
    action: str  # "skip", "alert", "opened", "failed"
    amount: float = 0.0
    is_live_open: bool = False


def _execute_signal(
    sig: Signal,
    strategy_name: str,
    strategy,
    strategy_meta_item: dict,
    execution_decision,
    policy,
    broker,
    live_broker,
    db: FactoryDB,
    run_id: str,
    meta: dict,
    market_index: dict,
    exposure_by_strategy: dict,
    exposure_by_window: dict,
    alert_signals: list,
    dry_run: bool,
    skip_cooldown: bool = False,
    extra_log_details: dict | None = None,
) -> _ExecuteResult:
    """Shared execution logic for a single signal. Returns result indicating what happened."""
    log_details = extra_log_details or {}

    if execution_decision.action == "skip":
        db.log_decision(run_id, "environment", "skip", strategy=strategy_name, market_id=sig.market_id, reason=execution_decision.reason)
        return _ExecuteResult("skip")

    if execution_decision.action == "alert":
        alert_signals.append(sig)
        print(f"  [{strategy_name}] ALERT {sig.outcome} {sig.market_title[:45]} | gap {sig.ev_pp:.0f}pp | {sig.confidence}")
        alert_details = {"ev_pp": sig.ev_pp, "confidence": sig.confidence, **log_details}
        if strategy_meta_item.get("alert_only") is not None:
            alert_details.update({
                "alert_only": strategy_meta_item.get("alert_only", False),
                "promotable": strategy_meta_item.get("promotable", False),
                "live_ready": strategy_meta_item.get("live_ready", False),
            })
        db.log_decision(run_id, "alert", "alert_only", strategy=strategy_name, market_id=sig.market_id,
                        reason=execution_decision.reason, details=alert_details)
        return _ExecuteResult("alert")

    is_live = execution_decision.action == "live"
    is_dual = execution_decision.action == "paper_and_live"

    if broker.has_position(sig.market_id, strategy_name):
        print(f"  [{strategy_name}] skip duplicate: {sig.market_title[:45]}")
        db.log_decision(run_id, "duplicate_check", "skip", strategy=strategy_name, market_id=sig.market_id, reason="already_open")
        return _ExecuteResult("skip")

    live_dup = is_dual and live_broker and live_broker.has_position(sig.market_id, strategy_name)

    if not skip_cooldown:
        cooldown_hours = getattr(strategy, "signal_cooldown_hours", 24.0)
        cooldown_consumed_only = execution_decision.action in ("paper", "live", "paper_and_live")
        if db.has_recent_signal(strategy_name, sig.market_id, hours=cooldown_hours, consumed_only=cooldown_consumed_only):
            print(f"  [{strategy_name}] skip cooldown ({cooldown_hours}h): {sig.market_title[:45]}")
            db.log_decision(run_id, "cooldown_check", "skip", strategy=strategy_name, market_id=sig.market_id, reason=f"signal_within_{cooldown_hours:.0f}h")
            return _ExecuteResult("skip")

    current_price = _current_yes_price(market_index, sig.market_id)
    if current_price is not None:
        drift = abs(current_price - sig.market_price)
        if drift > SIGNAL_PRICE_DRIFT_THRESHOLD:
            print(f"  [{strategy_name}] skip price_drift: {sig.market_title[:45]} | scan {sig.market_price:.2f} → now {current_price:.2f} ({drift:.2f})")
            db.log_decision(run_id, "price_drift", "skip", strategy=strategy_name, market_id=sig.market_id,
                            reason=f"price moved {drift:.2f} (scan {sig.market_price:.2f} → now {current_price:.2f})",
                            details={"scan_price": sig.market_price, "current_price": current_price, "drift": round(drift, 4), "threshold": SIGNAL_PRICE_DRIFT_THRESHOLD})
            return _ExecuteResult("skip")

    amount = strategy.size(sig)
    if amount < 1.0:
        db.log_decision(run_id, "size_check", "skip", strategy=strategy_name, market_id=sig.market_id, reason="tiny_size", details={"amount": amount})
        return _ExecuteResult("skip")

    allowed, reason = _can_open(amount, strategy_name, meta, exposure_by_strategy, exposure_by_window)
    if not allowed:
        print(f"  [{strategy_name}] skip capped: {sig.market_title[:45]} | {reason}")
        db.log_decision(run_id, "cap_check", "skip", strategy=strategy_name, market_id=sig.market_id, reason=reason,
                        details={"amount": amount, "strategy_exposure": exposure_by_strategy.get(strategy_name, 0.0),
                                 "window_exposure": exposure_by_window.get(strategy_meta_item.get("time_window", "unknown"), 0.0)})
        return _ExecuteResult("skip")

    # --- Open position ---
    def _get_market_dict():
        entry = market_index.get(sig.market_id, {})
        market = entry.get("market") or (entry.get("event", {}).get("markets") or [None])[0]
        if market:
            return market
        # For bare numeric IDs, scan the index for a composite key ending with :numeric_id
        if ":" not in sig.market_id:
            for key, val in market_index.items():
                if key.endswith(f":{sig.market_id}"):
                    market = val.get("market")
                    if market:
                        return market
        # Fallback: fetch the event by slug from Gamma API
        event_slug = sig.market_id.split(":")[0] if ":" in sig.market_id else None
        if not event_slug:
            return None
        try:
            events = fetch_by_slug(event_slug)
            if events:
                new_entries = build_market_index(events)
                market_index.update(new_entries)
                entry = market_index.get(sig.market_id, {})
                market = entry.get("market") or (entry.get("event", {}).get("markets") or [None])[0]
                if market:
                    print(f"  [{strategy_name}] fetched market data for {sig.market_id} via fallback")
                    return market
        except Exception as e:
            print(f"  [{strategy_name}] fallback fetch failed for {event_slug}: {e}")
        return None

    def _try_live_open():
        if not live_broker or dry_run or live_dup:
            return
        try:
            market_dict = _get_market_dict()
            live_trade = live_broker.open_position(sig, amount, market=market_dict)
            if live_trade:
                print(f"  [{strategy_name}] LIVE {sig.outcome} {sig.market_title[:45]} | EV +{sig.ev_pp:.0f}pp | ${amount} | {sig.confidence}")
                db.log_decision(run_id, "execution", "live_open", strategy=strategy_name, market_id=sig.market_id, reason="dual_execution",
                                details={"amount": amount, "ev_pp": sig.ev_pp, "confidence": sig.confidence, **log_details})
            else:
                print(f"  [{strategy_name}] LIVE FAILED {sig.outcome} {sig.market_title[:45]} | ${amount}")
                db.log_decision(run_id, "execution", "live_open_failed", strategy=strategy_name, market_id=sig.market_id, reason="broker_returned_none",
                                details={"amount": amount, "ev_pp": sig.ev_pp, "confidence": sig.confidence, **log_details})
        except Exception as e:
            print(f"  [{strategy_name}] LIVE ERROR {sig.market_title[:45]} | {e}")
            db.log_decision(run_id, "execution", "live_open_failed", strategy=strategy_name, market_id=sig.market_id, reason=f"exception: {e}",
                            details={"amount": amount, "ev_pp": sig.ev_pp, "confidence": sig.confidence, **log_details})

    if is_live:
        market_dict = _get_market_dict()
        trade = broker.open_position(sig, amount, market=market_dict)
        track = trade is not None
    elif is_dual:
        broker.open_position(sig, amount)
        track = True
        _try_live_open()
    else:
        broker.open_position(sig, amount)
        track = True

    if track:
        exposure_by_strategy[strategy_name] = exposure_by_strategy.get(strategy_name, 0.0) + amount
        window = strategy_meta_item.get("time_window", "unknown")
        exposure_by_window[window] = exposure_by_window.get(window, 0.0) + amount
        mode_label = "LIVE" if is_live else ("WOULD OPEN" if dry_run else "OPEN")
        print(f"  [{strategy_name}] {mode_label} {sig.outcome} {sig.market_title[:45]} | EV +{sig.ev_pp:.0f}pp | ${amount} | {sig.confidence}")
        db.log_decision(run_id, "execution", "live_open" if is_live else ("dry_open" if dry_run else "open"),
                        strategy=strategy_name, market_id=sig.market_id, reason=execution_decision.reason,
                        details={"amount": amount, "ev_pp": sig.ev_pp, "confidence": sig.confidence, **log_details})
        return _ExecuteResult("opened", amount=amount, is_live_open=is_live)
    elif is_live:
        print(f"  [{strategy_name}] LIVE FAILED {sig.outcome} {sig.market_title[:45]} | ${amount}")
        db.log_decision(run_id, "execution", "live_open_failed", strategy=strategy_name, market_id=sig.market_id, reason="broker_returned_none",
                        details={"amount": amount, "ev_pp": sig.ev_pp, "confidence": sig.confidence, **log_details})
        return _ExecuteResult("failed")
    return _ExecuteResult("skip")


def _apply_fast_dry_run_overrides(strategies: list, enabled: bool) -> list[tuple[object, dict]]:
    saved = []
    if not enabled:
        return saved
    for strategy in strategies:
        original = {}
        if hasattr(strategy, "fast_dry_run_topics"):
            original["_fast_dry_run_topics_override"] = getattr(strategy, "_fast_dry_run_topics_override", None)
            strategy._fast_dry_run_topics_override = getattr(strategy, "fast_dry_run_topics", 1)
        if hasattr(strategy, "fast_dry_run_candidates"):
            original["_fast_dry_run_candidates_override"] = getattr(strategy, "_fast_dry_run_candidates_override", None)
            strategy._fast_dry_run_candidates_override = getattr(strategy, "fast_dry_run_candidates", 4)
        if original:
            saved.append((strategy, original))
    return saved


def _restore_fast_dry_run_overrides(saved: list[tuple[object, dict]]):
    for strategy, original in saved:
        for attr, value in original.items():
            if value is None and hasattr(strategy, attr):
                delattr(strategy, attr)
            else:
                setattr(strategy, attr, value)


def _format_hourly_delta(snapshot: dict | None, previous_snapshot: dict | None) -> str | None:
    if not snapshot or not previous_snapshot:
        return None
    net_delta = round(float(snapshot.get("net_usdc") or 0) - float(previous_snapshot.get("net_usdc") or 0), 2)
    unrealized_delta = round(float(snapshot.get("unrealized_pnl_usdc") or 0) - float(previous_snapshot.get("unrealized_pnl_usdc") or 0), 2)
    sign = "+" if net_delta >= 0 else "-"
    marked = int(snapshot.get("marked_positions") or 0)
    stale = int(snapshot.get("stale_positions") or 0)
    coverage = f"marked {marked}"
    if stale:
        coverage += f", {stale} stale"
    return f"*1h delta:* {sign}${abs(net_delta):.2f} net · unrealized {unrealized_delta:+.2f} · {coverage}"


def _safe_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_market_observations(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for event in events:
        event_slug = event.get("slug") or ""
        event_volume = _safe_float(event.get("volume"))
        event_volume_24hr = _safe_float(event.get("volume24hr"))
        event_liquidity = _safe_float(event.get("liquidity") or event.get("liquidityClob"))
        close_time = event.get("endDate") or ""
        active_markets = [market for market in (event.get("markets", []) or []) if not market.get("closed")]
        primary_market = active_markets[0] if active_markets else ((event.get("markets", []) or [None])[0])
        primary_yes_price = None
        primary_best_bid = None
        primary_best_ask = None
        primary_spread = None
        if primary_market:
            prices = primary_market.get("outcomePrices")
            if isinstance(prices, str):
                try:
                    parsed = json.loads(prices)
                    primary_yes_price = _safe_float(parsed[0] if parsed else None)
                except Exception:
                    primary_yes_price = None
            elif isinstance(prices, list):
                primary_yes_price = _safe_float(prices[0] if prices else None)
            primary_best_bid = _safe_float(primary_market.get("bestBid"))
            primary_best_ask = _safe_float(primary_market.get("bestAsk"))
            primary_spread = _safe_float(primary_market.get("spread"))
        if event_slug:
            rows.append({
                "event_slug": event_slug,
                "market_id": event_slug,
                "market_slug": (primary_market or {}).get("slug") or "",
                "market_title": event.get("title") or "",
                "yes_price": primary_yes_price,
                "best_bid": primary_best_bid,
                "best_ask": primary_best_ask,
                "spread": primary_spread,
                "liquidity": event_liquidity,
                "volume": event_volume,
                "volume_24hr": event_volume_24hr,
                "close_time": close_time,
            })
        for market in event.get("markets", []) or []:
            market_id = str(market.get("id") or "")
            if not market_id:
                continue
            prices = market.get("outcomePrices")
            yes_price = None
            if isinstance(prices, str):
                try:
                    parsed = json.loads(prices)
                    yes_price = _safe_float(parsed[0] if parsed else None)
                except Exception:
                    yes_price = None
            elif isinstance(prices, list):
                yes_price = _safe_float(prices[0] if prices else None)
            rows.append({
                "event_slug": event_slug,
                "market_id": market_id if event_slug else market_id,
                "market_slug": market.get("slug") or "",
                "market_title": market.get("question") or event.get("title") or "",
                "yes_price": yes_price,
                "best_bid": _safe_float(market.get("bestBid")),
                "best_ask": _safe_float(market.get("bestAsk")),
                "spread": _safe_float(market.get("spread")),
                "liquidity": _safe_float(market.get("liquidity")) or event_liquidity,
                "volume": _safe_float(market.get("volume")) or event_volume,
                "volume_24hr": _safe_float(market.get("volume24hr")) or event_volume_24hr,
                "close_time": market.get("endDate") or close_time,
            })
            if event_slug:
                rows.append({
                    "event_slug": event_slug,
                    "market_id": f"{event_slug}:{market_id}",
                    "market_slug": market.get("slug") or "",
                    "market_title": market.get("question") or event.get("title") or "",
                    "yes_price": yes_price,
                    "best_bid": _safe_float(market.get("bestBid")),
                    "best_ask": _safe_float(market.get("bestAsk")),
                    "spread": _safe_float(market.get("spread")),
                    "liquidity": _safe_float(market.get("liquidity")) or event_liquidity,
                    "volume": _safe_float(market.get("volume")) or event_volume,
                    "volume_24hr": _safe_float(market.get("volume24hr")) or event_volume_24hr,
                    "close_time": market.get("endDate") or close_time,
                })
    return rows


def format_wa_summary(new_trades: list[tuple], closed_trades: list[dict], alert_signals: list[Signal], closed_count: int, stats: dict, now: str, skipped: list[str] | None = None, hour: int = 9, dry_run: bool = False, fast_dry_run: bool = False, hourly_delta: str | None = None, loss_streaks: dict | None = None, pipeline_health: list[dict] | None = None, environment: str = "paper", phase: str = "combined") -> str:
    if not isinstance(stats, dict) and isinstance(closed_count, dict):
        old_alert_signals = closed_trades
        old_closed_count = alert_signals if isinstance(alert_signals, int) else 0
        old_stats = closed_count
        old_now = stats
        old_skipped = now if isinstance(now, list) else []
        closed_trades = []
        alert_signals = old_alert_signals
        closed_count = old_closed_count
        stats = old_stats
        now = old_now
        skipped = old_skipped

    skipped = skipped or []
    new_by_strategy: dict[str, int] = {}
    for sig, _ in new_trades:
        new_by_strategy[sig.strategy] = new_by_strategy.get(sig.strategy, 0) + 1
    # Build environment/phase label for the notification title
    env_labels = []
    if environment == "research":
        env_labels.append("RESEARCH")
    elif phase == "execute":
        env_labels.append("EXECUTE")
    if dry_run:
        env_labels.append("DRY RUN")
    if fast_dry_run:
        env_labels.append("FAST")
    env_suffix = f" [{' / '.join(env_labels)}]" if env_labels else ""
    title = f"*PPLayouts — {now}{env_suffix}*"

    full_summary_window = hour == 9
    lines = [title + "\n"]

    if full_summary_window:
        lines.append(format_wa_table(stats, new_by_strategy))
        if hourly_delta:
            lines.append("\n" + hourly_delta)
        if closed_count:
            lines.append(f"\n{closed_count} position(s) {'would resolve' if dry_run else 'resolved'} this run.")
        if alert_signals:
            lines.append("\nAlerts:")
            for sig in alert_signals[:5]:
                lines.append(f"- [{sig.strategy}] {sig.outcome} {sig.market_title[:55]} | gap {sig.ev_pp:.0f}pp")
        if skipped:
            lines.append("\nSkipped this cycle: " + ", ".join(skipped))
        if loss_streaks:
            lines.append("\n⚠ *REVIEW NEEDED:*")
            for strat, info in loss_streaks.items():
                lines.append(f"- {strat}: {info['streak']} consecutive losses (${info['total_lost']:.2f}) — betting {info['last_outcome']}, consider flipping?")
        if pipeline_health:
            overdue = [p for p in pipeline_health if p["overdue"]]
            if overdue:
                lines.append("\n⚠ *PIPELINE ALERTS:*")
                for p in overdue:
                    if p["age_minutes"] is None:
                        lines.append(f"- {p['name']}: never run")
                    else:
                        hours = p["age_minutes"] // 60
                        mins = p["age_minutes"] % 60
                        age = f"{hours}h{mins:02d}m" if hours else f"{mins}m"
                        lines.append(f"- {p['name']}: overdue ({age} since last run)")
            else:
                lines.append("\nPipelines: all OK")
        lines.append("\n_/details <strategy> for trade breakdown_")
        return "\n".join(lines)

    if new_trades:
        lines.append("*Opened this run:*")
        for sig, amount in new_trades[:12]:
            lines.append(
                f"- [{sig.strategy}] {sig.outcome} {sig.market_title[:60]} | ${amount:.2f} | EV {sig.ev_pp:+.0f}pp"
            )
    else:
        lines.append("*Opened this run:* none")

    lines.append("")
    if closed_trades:
        lines.append(f"*Closed this run:* {'would resolve' if dry_run else 'resolved'}")
        for trade in closed_trades[:12]:
            side_label = trade['outcome']
            resolved_label = trade['winner']
            if resolved_label and resolved_label not in ('YES', 'NO') and side_label in ('YES', 'NO'):
                side_label = f"normalized {side_label}"
            lines.append(
                f"- [{trade['strategy']}] {trade['market_title'][:60]} | side {side_label} | resolved {resolved_label} | stake ${trade['amount_usdc']:.2f}"
            )
    else:
        lines.append("*Closed this run:* none")

    if hourly_delta:
        lines.append("")
        lines.append(hourly_delta)

    if alert_signals:
        lines.append("")
        lines.append(f"*Alerts this run:* {len(alert_signals)}")
        for sig in alert_signals[:3]:
            lines.append(f"- [{sig.strategy}] {sig.outcome} {sig.market_title[:55]} | gap {sig.ev_pp:.0f}pp")

    if loss_streaks:
        lines.append("")
        lines.append("⚠ *REVIEW NEEDED:*")
        for strat, info in loss_streaks.items():
            lines.append(f"- {strat}: {info['streak']} consecutive losses (${info['total_lost']:.2f}) — betting {info['last_outcome']}, consider flipping?")

    if pipeline_health:
        overdue = [p for p in pipeline_health if p["overdue"]]
        if overdue:
            lines.append("")
            lines.append("⚠ *PIPELINE ALERTS:*")
            for p in overdue:
                if p["age_minutes"] is None:
                    lines.append(f"- {p['name']}: never run")
                else:
                    hours = p["age_minutes"] // 60
                    mins = p["age_minutes"] % 60
                    age = f"{hours}h{mins:02d}m" if hours else f"{mins}m"
                    lines.append(f"- {p['name']}: overdue ({age} since last run)")

    return "\n".join(lines)


def _current_yes_price(market_index: dict, market_id: str) -> float | None:
    """Look up the current YES price for a market from the fresh market index."""
    entry = market_index.get(market_id)
    if not entry:
        return None
    market = entry.get("market")
    if not market:
        # event-level entry: try first active market
        event = entry.get("event", {})
        active = [m for m in (event.get("markets") or []) if not m.get("closed")]
        market = active[0] if active else ((event.get("markets") or [None])[0])
    if not market:
        return None
    prices = market.get("outcomePrices")
    if isinstance(prices, str):
        try:
            parsed = json.loads(prices)
            return _safe_float(parsed[0] if parsed else None)
        except Exception:
            return None
    elif isinstance(prices, list):
        return _safe_float(prices[0] if prices else None)
    return None


def _reconstruct_signal(row: dict) -> Signal:
    """Rebuild a Signal dataclass from a DB signals row."""
    return Signal(
        strategy=row["strategy"],
        market_id=row["market_id"],
        market_title=row["market_title"],
        outcome=row["outcome"],
        market_price=float(row["market_price"]),
        p_hat=float(row["p_hat"]),
        ev_pp=float(row["ev_pp"]),
        confidence=row.get("confidence") or "medium",
        closes=row.get("closes") or "",
        url=row.get("url") or "",
        rationale=row.get("rationale") or "",
    )


def run(environment: str = "paper", dry_run: bool = False, send: bool = True, fast_dry_run: bool = False, phase: str = "combined"):
    policy = get_environment_policy(environment)
    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M")
    flags = []
    if policy.name != "paper":
        flags.append(policy.name.upper())
    if phase == "execute":
        flags.append("EXECUTE")
    if dry_run:
        flags.append("DRY RUN")
    if fast_dry_run:
        flags.append("FAST")
    flag_str = f" [{' / '.join(flags)}]" if flags else ""
    mode_parts = [policy.name]
    if phase == "execute":
        mode_parts.append("execute")
    if fast_dry_run:
        mode_parts.append("fast_dry_run")
    elif dry_run:
        mode_parts.append("dry_run")
    mode = "_".join(mode_parts)
    print(f"\n{'='*60}")
    print(f"POLYMARKET FACTORY — {now}{flag_str}")
    print(f"{'='*60}\n")

    reset_circuit_breaker()
    db = FactoryDB()
    run_id = db.start_run(mode=mode)
    db.log_event(run_id, "info", "run_started", payload={"mode": mode, "environment": policy.name})
    lock_acquired = False

    live_broker: LiveBroker | None = None
    if policy.name == "research":
        base_broker = ResearchBroker()
    elif policy.name == "live":
        base_broker = LiveBroker(db=db, run_id=run_id)
    else:
        base_broker = PaperBroker(db=db, run_id=run_id)
        # Create a live broker alongside paper broker for dual-execution of live strategies
        # Only if CLOB credentials are available (VM has them, Mac does not)
        if os.environ.get("POLYMARKET_WALLET_PRIVATE_KEY"):
            live_broker = LiveBroker(db=db, run_id=run_id)
    broker = DryRunBroker(base_broker) if dry_run else base_broker
    meta = strategy_metadata()
    saved_overrides = _apply_fast_dry_run_overrides(STRATEGIES, enabled=fast_dry_run)
    markets_fetched = 0
    closed_count = 0
    new_positions_count = 0

    try:
        if not dry_run:
            lock_acquired = db.acquire_run_lock(policy.lock_name, run_id)
            if not lock_acquired:
                msg = f"another {policy.name} run already holds the lock"
                print(f"Abort: {msg}")
                db.log_decision(run_id, "run_lock", "skip", reason=msg)
                db.finish_run(run_id, status="aborted", notes=msg)
                return
            db.log_decision(run_id, "run_lock", "acquired", reason=policy.lock_name)
        else:
            db.log_decision(run_id, "run_lock", "bypass", reason="dry_run")

        if policy.resolves_positions:
            print("Checking open positions for resolution...")
            closed_count, closed_trades = resolve_open_positions(broker, dry_run=dry_run, db=db, run_id=run_id)
            # Also resolve live positions during paper runs
            if live_broker and not dry_run:
                live_closed, live_closed_trades = resolve_open_positions(live_broker, dry_run=False, db=db, run_id=run_id)
                closed_count += live_closed
                closed_trades.extend(live_closed_trades)
            print(f"  {closed_count} {'would resolve' if dry_run else 'resolved'}.\n")
        else:
            closed_trades = []
            print("Skipping open-position resolution in research environment.\n")

        # Fast pass: fetch 1000 markets for price observations
        print("Fast pass: fetching 1000 markets for observations...", end=" ", flush=True)
        try:
            all_markets = fetch_top_paginated(total=1000)
        except Exception as e:
            print(f"FAILED after retries: {e}")
            db.log_event(run_id, "error", f"fetch_top_paginated failed: {e}")
            db.finish_run(run_id, status="failed", markets_fetched=0, closed_count=closed_count, new_positions_count=0, notes=f"fetch failed: {e}")
            return
        print(f"{len(all_markets)} markets.")
        db.log_market_observations(run_id, _extract_market_observations(all_markets))
        db.log_event(run_id, "info", "observations_logged", payload={"count": len(all_markets)})

        # Slow pass: use top 500 for strategies + execution
        markets = all_markets[:500]
        markets_fetched = len(markets)
        print(f"Slow pass: running strategies on top {markets_fetched} markets.\n")
        db.log_event(run_id, "info", "markets_fetched", payload={"count": markets_fetched, "observed": len(all_markets)})
        db.log_market_snapshot_archive(run_id, markets, source="fetch_top")

        new_trades: list[tuple[Signal, float]] = []
        alert_signals: list[Signal] = []
        skipped_this_cycle: list[str] = []
        exposure_by_strategy, exposure_by_window = _current_exposure_by_strategy_and_window(broker, meta)
        # Merge live exposure into caps so dual strategies don't exceed limits
        if live_broker:
            live_by_strategy, live_by_window = _current_exposure_by_strategy_and_window(live_broker, meta)
            for k, v in live_by_strategy.items():
                exposure_by_strategy[k] = exposure_by_strategy.get(k, 0.0) + v
            for k, v in live_by_window.items():
                exposure_by_window[k] = exposure_by_window.get(k, 0.0) + v
        market_index = build_market_index(markets)

        # Auto-close unhedged partial-fill positions (live only)
        if not dry_run and hasattr(base_broker, "try_close_unhedged"):
            for t in base_broker.get_open_positions():
                if t.get("outcome") == "PARTIAL_YES_UNHEDGED":
                    base_broker.try_close_unhedged(t, market_index)
        if not dry_run and live_broker:
            for t in live_broker.get_open_positions():
                if t.get("outcome") == "PARTIAL_YES_UNHEDGED":
                    live_broker.try_close_unhedged(t, market_index)

        # Build strategy lookup for execute phase
        strategy_by_name = {s.name: s for s in STRATEGIES}

        if phase == "execute":
            # --- Execute-only: read cached signals from scan phase ---
            cached_rows = db.get_unconsumed_signals(max_age_hours=2.0)
            consumed_ids: list[int] = []
            if not cached_rows:
                print("No cached signals to execute (scan may not have run).\n")
                db.log_event(run_id, "info", "no_cached_signals")
            else:
                print(f"Loaded {len(cached_rows)} cached signals from scan phase.\n")
                db.log_event(run_id, "info", "cached_signals_loaded", payload={"count": len(cached_rows)})

            for row in cached_rows:
                consumed_ids.append(row["id"])
                sig = _reconstruct_signal(row)
                strategy = strategy_by_name.get(sig.strategy)
                if not strategy:
                    db.log_decision(run_id, "execute", "skip", strategy=sig.strategy, market_id=sig.market_id, reason="unknown_strategy")
                    continue

                strategy_meta_item = meta.get(sig.strategy, {})
                execution_decision = classify_strategy_execution(policy, strategy, strategy_meta_item)
                result = _execute_signal(
                    sig=sig, strategy_name=sig.strategy, strategy=strategy, strategy_meta_item=strategy_meta_item,
                    execution_decision=execution_decision, policy=policy, broker=broker, live_broker=live_broker,
                    db=db, run_id=run_id, meta=meta, market_index=market_index,
                    exposure_by_strategy=exposure_by_strategy, exposure_by_window=exposure_by_window,
                    alert_signals=alert_signals, dry_run=dry_run,
                    extra_log_details={"phase": "execute"},
                )
                if result.action == "opened":
                    new_trades.append((sig, result.amount))
                    new_positions_count += 1

            if consumed_ids and not dry_run:
                db.mark_signals_consumed(consumed_ids, run_id)
                db.log_event(run_id, "info", "signals_consumed", payload={"count": len(consumed_ids)})

        else:
            # --- Combined mode: scan + execute in one pass ---
            for strategy in STRATEGIES:
                strategy_meta_item = meta.get(strategy.name, {})
                if fast_dry_run and strategy.name == "ev_news":
                    print(f"Skipping [{strategy.name}] in fast dry run (expensive LLM path).")
                    skipped_this_cycle.append(f"{strategy.name}[fast-skip]")
                    db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="fast_dry_run", details={"time_window": strategy_meta_item.get("time_window")})
                    continue
                if strategy_meta_item.get("paused") or getattr(strategy, "paused", False):
                    print(f"Skipping [{strategy.name}] (paused).")
                    skipped_this_cycle.append(f"{strategy.name}[paused]")
                    db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="paused")
                    continue
                # Skip cadence check for live runs — they run once/day, all strategies should participate.
                if policy.name != "live" and not should_run_in_cycle(strategy_meta_item.get("time_window", "unknown"), now_dt.hour):
                    print(f"Skipping [{strategy.name}] this cycle ({strategy_meta_item.get('time_window')}).")
                    skipped_this_cycle.append(f"{strategy.name}[{strategy_meta_item.get('time_window')}]")
                    db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="cadence", details={"time_window": strategy_meta_item.get("time_window"), "hour": now_dt.hour})
                    continue

                print(f"Running [{strategy.name}] ({strategy_meta_item.get('edge_type','other')}/{strategy_meta_item.get('time_window','?')})...")
                db.log_event(run_id, "info", "strategy_started", strategy=strategy.name, payload={"edge_type": strategy_meta_item.get("edge_type"), "time_window": strategy_meta_item.get("time_window")})
                try:
                    signals = strategy.scan(markets)
                except Exception as e:
                    print(f"  Error in {strategy.name}.scan(): {e}")
                    db.log_event(run_id, "error", f"strategy scan error: {e}", strategy=strategy.name)
                    db.log_decision(run_id, "strategy_scan", "error", strategy=strategy.name, reason=str(e))
                    continue

                for sig in signals:
                    sig_dict = _signal_to_dict(sig)
                    db.log_signal(run_id, strategy.name, sig_dict, time_window=strategy_meta_item.get("time_window"), edge_type=strategy_meta_item.get("edge_type"), decision_status="generated")
                    execution_snapshot = snapshot_for_signal(sig, strategy, market_index)
                    db.log_signal_execution_check(run_id, execution_snapshot.as_dict())

                    execution_decision = classify_strategy_execution(policy, strategy, strategy_meta_item)
                    is_live_or_dual = execution_decision.action in ("live", "paper_and_live")
                    result = _execute_signal(
                        sig=sig, strategy_name=strategy.name, strategy=strategy, strategy_meta_item=strategy_meta_item,
                        execution_decision=execution_decision, policy=policy, broker=broker, live_broker=live_broker,
                        db=db, run_id=run_id, meta=meta, market_index=market_index,
                        exposure_by_strategy=exposure_by_strategy, exposure_by_window=exposure_by_window,
                        alert_signals=alert_signals, dry_run=dry_run,
                        skip_cooldown=is_live_or_dual,
                        extra_log_details={"mode": "live" if execution_decision.action == "live" else "paper", "environment": policy.name},
                    )
                    if result.action == "opened":
                        new_trades.append((sig, result.amount))
                        new_positions_count += 1

                print()
                _log_strategy_details(db, run_id, strategy)
                db.log_event(run_id, "info", "strategy_finished", strategy=strategy.name, payload={"signals": len(signals)})

        # Check for loss streaks — flag strategies that need review (skip killed ones)
        loss_streaks = db.get_loss_streaks(min_streak=10)
        loss_streaks = {s: info for s, info in loss_streaks.items() if s in ACTIVE_STRATEGIES} if loss_streaks else {}
        if loss_streaks:
            for strat, info in loss_streaks.items():
                print(f"  ⚠ REVIEW {strat}: {info['streak']} consecutive losses (${info['total_lost']:.2f} lost, last side: {info['last_outcome']})")
                db.log_decision(run_id, "review", "loss_streak", strategy=strat, reason=f"{info['streak']} consecutive losses", details=info)

        stats = summary(broker)
        portfolio_snapshot = snapshot_open_positions(broker, market_index)
        previous_snapshot = db.get_latest_portfolio_snapshot_before((now_dt - timedelta(hours=1)).isoformat(timespec="seconds"))
        hourly_delta = _format_hourly_delta(portfolio_snapshot, previous_snapshot)
        if not dry_run and policy.records_portfolio_snapshots:
            db.log_portfolio_snapshot(run_id, portfolio_snapshot)
            db.log_event(run_id, "info", "portfolio_snapshot", payload=portfolio_snapshot)
        print(format_summary(stats))
        pipeline_health = db.get_pipeline_health()
        wa_msg = format_wa_summary(new_trades, closed_trades, alert_signals, closed_count, stats, now, skipped_this_cycle, now_dt.hour, dry_run=dry_run, fast_dry_run=fast_dry_run, hourly_delta=hourly_delta, loss_streaks=loss_streaks, pipeline_health=pipeline_health, environment=policy.name, phase=phase)
        if dry_run or not send:
            print("\n--- WHATSAPP PREVIEW ---")
            print(wa_msg)
            print("--- END WHATSAPP PREVIEW ---")
            sent = True
            db.log_decision(run_id, "notify", "preview_only", reason="dry_or_nosend")
        else:
            notify_report = send_notification(wa_msg)
            sent = bool(notify_report.get("any_sent"))
            db.log_decision(
                run_id,
                "notify",
                "sent" if sent else "failed",
                reason="notification_send",
                details=notify_report,
            )
            channel_bits = []
            for name, status in notify_report.get("channels", {}).items():
                configured = notify_report.get("configured", {}).get(name, {}).get("configured", False)
                attempts = int(status.get("attempts") or 0)
                if status.get("sent"):
                    if attempts > 1:
                        channel_bits.append(f"{name}:sent_after_{attempts}_attempts")
                    else:
                        channel_bits.append(f"{name}:sent")
                elif configured:
                    label = f"{name}:failed"
                    if attempts:
                        label += f"_after_{attempts}_attempts"
                    channel_bits.append(label)
                else:
                    channel_bits.append(f"{name}:unconfigured")
            if channel_bits:
                print("Notification detail: " + ", ".join(channel_bits))

        print(f"\n{'Dry run preview generated' if dry_run or not send else 'Notification sent'} ✓" if sent else "\nNotification FAILED — check notify channels.")

        if not dry_run:
            cleanup = db.cleanup_old_snapshots()
            total_cleaned = cleanup["archives_deleted"] + cleanup["observations_deleted"]
            if total_cleaned:
                print(f"Retention cleanup: {cleanup['archives_deleted']} archives, {cleanup['observations_deleted']} observations deleted.")
                db.log_event(run_id, "info", "retention_cleanup", payload=cleanup)

        print(f"\n{'='*60}\n")
        db.finish_run(run_id, status="success", markets_fetched=markets_fetched, closed_count=closed_count, new_positions_count=new_positions_count)
    except Exception as e:
        db.log_event(run_id, "error", f"run_failed: {e}")
        db.finish_run(run_id, status="failed", markets_fetched=markets_fetched, closed_count=closed_count, new_positions_count=new_positions_count, notes=str(e))
        raise
    finally:
        if lock_acquired:
            db.release_run_lock(policy.lock_name, run_id)
        _restore_fast_dry_run_overrides(saved_overrides)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket Factory runner")
    parser.add_argument("--phase", choices=["combined", "execute"], default="combined",
                        help="combined (default): scan + execute; execute: read cached signals only")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-send", action="store_true")
    args = parser.parse_args()
    run(environment=os.environ.get("FACTORY_ENV", "paper"),
        dry_run=args.dry_run, send=not args.no_send, phase=args.phase)

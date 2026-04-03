"""
Main runner — called 3x/day by launchd.
1. Fetch market snapshot
2. Run each strategy → collect signals
3. Size + open positions (skip duplicates)
4. Check open positions → close resolved ones
5. Send WhatsApp summary

Supports `dry_run=True` for a safe manual pass with no writes and no sends.
Supports `fast_dry_run=True` to aggressively trim slow strategy work for debugging.
Includes live-run locking + strategy detail logging.
"""
import os
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta

from .broker import PaperBroker
from .db import FactoryDB
from .environment import classify_strategy_execution, get_environment_policy
from .live_broker import LiveBroker
from .execution import build_market_index, snapshot_for_signal
from .feed import fetch_top, fetch_closed, get_market_winner, get_submarket_outcome
from .models import Signal
from .notify import send_whatsapp
from .portfolio import summary, format_summary, format_wa_table, snapshot_open_positions
from .strategies import STRATEGIES
from .strategy_meta import strategy_metadata, should_run_in_cycle


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
    elif strategy.name == "resolution_hunter":
        for row in getattr(strategy, "last_check_details", []):
            db.log_resolution_hunter_check(run_id, row)
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
            event_slug, submarket_id = market_id, None
        try:
            events = fetch_closed(event_slug)
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


def format_wa_summary(new_trades: list[tuple], closed_trades: list[dict], alert_signals: list[Signal], closed_count: int, stats: dict, now: str, skipped: list[str] | None = None, hour: int = 9, dry_run: bool = False, fast_dry_run: bool = False, hourly_delta: str | None = None) -> str:
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
    title = f"*PPLayouts — {now}*"
    if dry_run:
        title += " [DRY RUN]"
    if fast_dry_run:
        title += " [FAST]"

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

    return "\n".join(lines)


def run(environment: str = "paper", dry_run: bool = False, send: bool = True, fast_dry_run: bool = False):
    policy = get_environment_policy(environment)
    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M")
    flags = []
    if policy.name != "paper":
        flags.append(policy.name.upper())
    if dry_run:
        flags.append("DRY RUN")
    if fast_dry_run:
        flags.append("FAST")
    flag_str = f" [{' / '.join(flags)}]" if flags else ""
    mode_parts = [policy.name]
    if fast_dry_run:
        mode_parts.append("fast_dry_run")
    elif dry_run:
        mode_parts.append("dry_run")
    mode = "_".join(mode_parts)
    print(f"\n{'='*60}")
    print(f"POLYMARKET FACTORY — {now}{flag_str}")
    print(f"{'='*60}\n")

    db = FactoryDB()
    run_id = db.start_run(mode=mode)
    db.log_event(run_id, "info", "run_started", payload={"mode": mode, "environment": policy.name})
    lock_acquired = False

    if policy.name == "research":
        base_broker = ResearchBroker()
    elif policy.name == "live":
        base_broker = LiveBroker(db=db, run_id=run_id)
    else:
        base_broker = PaperBroker(run_id=run_id)
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
            print(f"  {closed_count} {'would resolve' if dry_run else 'resolved'}.\n")
        else:
            closed_trades = []
            print("Skipping open-position resolution in research environment.\n")

        print("Fetching market snapshot...", end=" ", flush=True)
        markets = fetch_top(limit=100)
        markets_fetched = len(markets)
        print(f"{markets_fetched} markets.\n")
        db.log_event(run_id, "info", "markets_fetched", payload={"count": markets_fetched})
        db.log_market_snapshot_archive(run_id, markets, source="fetch_top")
        db.log_market_observations(run_id, _extract_market_observations(markets))

        new_trades: list[tuple[Signal, float]] = []
        alert_signals: list[Signal] = []
        skipped_this_cycle: list[str] = []
        exposure_by_strategy, exposure_by_window = _current_exposure_by_strategy_and_window(broker, meta)
        market_index = build_market_index(markets)

        for strategy in STRATEGIES:
            strategy_meta = meta.get(strategy.name, {})
            if fast_dry_run and strategy.name == "ev_news":
                print(f"Skipping [{strategy.name}] in fast dry run (expensive LLM path).")
                skipped_this_cycle.append(f"{strategy.name}[fast-skip]")
                db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="fast_dry_run", details={"time_window": strategy_meta.get("time_window")})
                continue
            if strategy_meta.get("paused") or getattr(strategy, "paused", False):
                print(f"Skipping [{strategy.name}] (paused).")
                skipped_this_cycle.append(f"{strategy.name}[paused]")
                db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="paused")
                continue
            if not should_run_in_cycle(strategy_meta.get("time_window", "unknown"), now_dt.hour):
                print(f"Skipping [{strategy.name}] this cycle ({strategy_meta.get('time_window')}).")
                skipped_this_cycle.append(f"{strategy.name}[{strategy_meta.get('time_window')}]")
                db.log_decision(run_id, "cycle_skip", "skip", strategy=strategy.name, reason="cadence", details={"time_window": strategy_meta.get("time_window"), "hour": now_dt.hour})
                continue

            print(f"Running [{strategy.name}] ({strategy_meta.get('edge_type','other')}/{strategy_meta.get('time_window','?')})...")
            db.log_event(run_id, "info", "strategy_started", strategy=strategy.name, payload={"edge_type": strategy_meta.get("edge_type"), "time_window": strategy_meta.get("time_window")})
            try:
                signals = strategy.scan(markets)
            except Exception as e:
                print(f"  Error in {strategy.name}.scan(): {e}")
                db.log_event(run_id, "error", f"strategy scan error: {e}", strategy=strategy.name)
                db.log_decision(run_id, "strategy_scan", "error", strategy=strategy.name, reason=str(e))
                continue

            for sig in signals:
                sig_dict = _signal_to_dict(sig)
                db.log_signal(run_id, strategy.name, sig_dict, time_window=strategy_meta.get("time_window"), edge_type=strategy_meta.get("edge_type"), decision_status="generated")
                execution_snapshot = snapshot_for_signal(sig, strategy, market_index)
                db.log_signal_execution_check(run_id, execution_snapshot.as_dict())

                execution_decision = classify_strategy_execution(policy, strategy, strategy_meta)

                if execution_decision.action == "skip":
                    db.log_decision(run_id, "environment", "skip", strategy=strategy.name, market_id=sig.market_id, reason=execution_decision.reason)
                    continue

                if execution_decision.action == "alert":
                    alert_signals.append(sig)
                    print(f"  [{strategy.name}] ALERT {sig.outcome} {sig.market_title[:45]} | gap {sig.ev_pp:.0f}pp | {sig.confidence}")
                    db.log_decision(
                        run_id,
                        "alert",
                        "alert_only",
                        strategy=strategy.name,
                        market_id=sig.market_id,
                        reason=execution_decision.reason,
                        details={
                            "ev_pp": sig.ev_pp,
                            "confidence": sig.confidence,
                            "alert_only": strategy_meta.get("alert_only", False),
                            "promotable": strategy_meta.get("promotable", False),
                            "live_ready": strategy_meta.get("live_ready", False),
                        },
                    )
                    continue

                is_live = execution_decision.action == "live"
                active_broker = broker

                if active_broker.has_position(sig.market_id, strategy.name):
                    print(f"  [{strategy.name}] skip duplicate: {sig.market_title[:45]}")
                    db.log_decision(run_id, "duplicate_check", "skip", strategy=strategy.name, market_id=sig.market_id, reason="already_open")
                    continue
                amount = strategy.size(sig)
                if amount < 1.0:
                    print(f"  [{strategy.name}] skip tiny size (${amount}): {sig.market_title[:45]}")
                    db.log_decision(run_id, "size_check", "skip", strategy=strategy.name, market_id=sig.market_id, reason="tiny_size", details={"amount": amount})
                    continue
                allowed, reason = _can_open(amount, strategy.name, meta, exposure_by_strategy, exposure_by_window)
                if not allowed:
                    print(f"  [{strategy.name}] skip capped: {sig.market_title[:45]} | {reason}")
                    db.log_decision(run_id, "cap_check", "skip", strategy=strategy.name, market_id=sig.market_id, reason=reason, details={"amount": amount, "strategy_exposure": exposure_by_strategy.get(strategy.name, 0.0), "window_exposure": exposure_by_window.get(strategy_meta.get("time_window", "unknown"), 0.0)})
                    continue

                if is_live:
                    market_entry = market_index.get(sig.market_id, {})
                    market_dict = market_entry.get("market") or (market_entry.get("event", {}).get("markets") or [None])[0]
                    trade = active_broker.open_position(sig, amount, market=market_dict)
                    track = trade is not None
                else:
                    active_broker.open_position(sig, amount)
                    track = True

                if track:
                    exposure_by_strategy[strategy.name] = exposure_by_strategy.get(strategy.name, 0.0) + amount
                    exposure_by_window[strategy_meta.get("time_window", "unknown")] = exposure_by_window.get(strategy_meta.get("time_window", "unknown"), 0.0) + amount
                    new_trades.append((sig, amount))
                    new_positions_count += 1
                    mode_label = "LIVE" if is_live else ("WOULD OPEN" if dry_run else "OPEN")
                    print(f"  [{strategy.name}] {mode_label} {sig.outcome} {sig.market_title[:45]} | EV +{sig.ev_pp:.0f}pp | ${amount} | {sig.confidence}")
                    db.log_decision(run_id, "execution", "live_open" if is_live else ("dry_open" if dry_run else "open"), strategy=strategy.name, market_id=sig.market_id, reason=execution_decision.reason, details={"amount": amount, "ev_pp": sig.ev_pp, "confidence": sig.confidence, "mode": "live" if is_live else "paper", "environment": policy.name})

            print()
            _log_strategy_details(db, run_id, strategy)
            db.log_event(run_id, "info", "strategy_finished", strategy=strategy.name, payload={"signals": len(signals)})

        stats = summary(broker)
        portfolio_snapshot = snapshot_open_positions(broker, market_index)
        previous_snapshot = db.get_latest_portfolio_snapshot_before((now_dt - timedelta(hours=1)).isoformat(timespec="seconds"))
        hourly_delta = _format_hourly_delta(portfolio_snapshot, previous_snapshot)
        if not dry_run and policy.records_portfolio_snapshots:
            db.log_portfolio_snapshot(run_id, portfolio_snapshot)
            db.log_event(run_id, "info", "portfolio_snapshot", payload=portfolio_snapshot)
        print(format_summary(stats))
        wa_msg = format_wa_summary(new_trades, closed_trades, alert_signals, closed_count, stats, now, skipped_this_cycle, now_dt.hour, dry_run=dry_run, fast_dry_run=fast_dry_run, hourly_delta=hourly_delta)
        if dry_run or not send:
            print("\n--- WHATSAPP PREVIEW ---")
            print(wa_msg)
            print("--- END WHATSAPP PREVIEW ---")
            sent = True
            db.log_decision(run_id, "notify", "preview_only", reason="dry_or_nosend")
        else:
            sent = send_whatsapp(wa_msg)
            db.log_decision(run_id, "notify", "sent" if sent else "failed", reason="whatsapp_send")

        print(f"\n{'Dry run preview generated' if dry_run or not send else 'WhatsApp notification sent'} ✓" if sent else "\nWhatsApp notification FAILED — check openclaw.")
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
    run(environment=os.environ.get("FACTORY_ENV", "paper"))

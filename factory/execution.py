"""Shared execution-reality helpers for Phase A signal instrumentation.

This layer is intentionally conservative:
- it captures observed quote fields when available
- it produces simple, labeled fill proxies for a few size buckets
- it avoids pretending we have a full order-book simulator
"""
from __future__ import annotations

from dataclasses import dataclass

SIZE_BUCKETS = (10.0, 25.0, 50.0, 100.0, 250.0)


@dataclass
class ExecutionSnapshot:
    strategy: str
    market_id: str
    market_title: str
    outcome: str
    quote_price: float
    best_bid: float | None
    best_ask: float | None
    quoted_spread: float | None
    order_min_size: float | None
    liquidity_proxy: float | None
    source_confidence: str
    fill_price_10: float
    fill_price_25: float
    fill_price_50: float
    fill_price_100: float
    fill_price_250: float
    slippage_10_pp: float
    slippage_25_pp: float
    slippage_50_pp: float
    slippage_100_pp: float
    slippage_250_pp: float
    ev_after_slippage_10_pp: float
    ev_after_slippage_25_pp: float
    ev_after_slippage_50_pp: float
    ev_after_slippage_100_pp: float
    ev_after_slippage_250_pp: float
    max_size_positive_ev: float
    max_size_above_min_edge: float

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _safe_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(min(max(value, 0.001), 0.999), 4)


def _book_for_outcome(
    outcome: str,
    best_bid: float | None,
    best_ask: float | None,
) -> tuple[float | None, float | None]:
    if outcome != "NO":
        return best_bid, best_ask
    no_best_bid = _normalize_price(None if best_ask is None else 1 - best_ask)
    no_best_ask = _normalize_price(None if best_bid is None else 1 - best_bid)
    return no_best_bid, no_best_ask


def build_market_index(events: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for event in events:
        slug = event.get("slug") or ""
        if slug:
            index[slug] = {"event": event, "market": None}
        for market in event.get("markets", []) or []:
            market_slug = market.get("slug") or ""
            market_id = str(market.get("id") or "")
            if market_slug:
                index[market_slug] = {"event": event, "market": market}
            if slug and market_id:
                index[f"{slug}:{market_id}"] = {"event": event, "market": market}
    return index


def _pick_market(signal, market_index: dict[str, dict]) -> tuple[dict | None, dict | None]:
    direct = market_index.get(signal.market_id)
    if direct:
        return direct.get("event"), direct.get("market")

    if ":" in signal.market_id:
        event_slug, market_id = signal.market_id.split(":", 1)
        event = market_index.get(event_slug, {}).get("event")
        if event:
            for market in event.get("markets", []) or []:
                if str(market.get("id")) == market_id:
                    return event, market
            for market in event.get("markets", []) or []:
                if (market.get("question") or "")[:100] == signal.market_title[:100]:
                    return event, market
            return event, None

    event = market_index.get(signal.market_id, {}).get("event")
    if event:
        markets = event.get("markets", []) or []
        active = [m for m in markets if not m.get("closed")]
        if len(active) == 1:
            return event, active[0]
        for market in active:
            question = (market.get("question") or "")[:100]
            if question == signal.market_title[:100]:
                return event, market
        return event, active[0] if active else None

    return None, None


def _liquidity_proxy(event: dict | None, market: dict | None) -> float | None:
    if market:
        for key in ("liquidity", "volume24hr", "volumeClob", "volume", "volumeNum"):
            value = _safe_float(market.get(key))
            if value and value > 0:
                if key.startswith("volume"):
                    return round(max(5.0, min(value * 0.01, 1000.0)), 2)
                return round(value, 2)
    if event:
        for key in ("liquidity", "liquidityClob", "volume24hr", "volume"):
            value = _safe_float(event.get(key))
            if value and value > 0:
                if key.startswith("volume"):
                    return round(max(5.0, min(value * 0.01, 1000.0)), 2)
                return round(value, 2)
    return None


def _source_confidence(best_bid: float | None, best_ask: float | None, liquidity_proxy: float | None) -> str:
    score = 0
    if best_bid is not None:
        score += 1
    if best_ask is not None:
        score += 1
    if liquidity_proxy is not None:
        score += 1
    if score >= 3:
        return "medium"
    if score == 2:
        return "low"
    return "very_low"


def _estimate_fill(quote_price: float, best_bid: float | None, best_ask: float | None, spread: float | None, liquidity_proxy: float | None, amount: float) -> float:
    # Start from the most conservative available buy-side price.
    base = best_ask if best_ask is not None else quote_price

    effective_spread = spread
    if effective_spread is None:
        if best_bid is not None and best_ask is not None:
            effective_spread = max(best_ask - best_bid, 0.0)
        else:
            effective_spread = max(0.01, min(0.08, quote_price * 0.08))

    depth = max(liquidity_proxy or 10.0, 1.0)
    impact = min(0.25, 0.06 * (amount / depth) ** 0.7)
    half_spread_penalty = effective_spread * 0.5 if best_ask is None else 0.0
    return min(0.999, max(0.001, base + half_spread_penalty + impact))


def snapshot_for_signal(signal, strategy, market_index: dict[str, dict]) -> ExecutionSnapshot:
    event, market = _pick_market(signal, market_index)
    quote_price = round(float(signal.market_price), 4)
    best_bid = _normalize_price(_safe_float((market or {}).get("bestBid")))
    best_ask = _normalize_price(_safe_float((market or {}).get("bestAsk")))
    best_bid, best_ask = _book_for_outcome(signal.outcome, best_bid, best_ask)
    spread = _safe_float((market or {}).get("spread"))
    if spread is None and best_bid is not None and best_ask is not None:
        spread = round(max(best_ask - best_bid, 0.0), 4)
    elif spread is not None:
        spread = round(max(spread, 0.0), 4)

    order_min_size = _safe_float((market or {}).get("orderMinSize"))
    liquidity_proxy = _liquidity_proxy(event, market)
    source_confidence = _source_confidence(best_bid, best_ask, liquidity_proxy)

    fills = {}
    slips = {}
    evs = {}
    for amount in SIZE_BUCKETS:
        fill = round(_estimate_fill(quote_price, best_bid, best_ask, spread, liquidity_proxy, amount), 4)
        slip_pp = round((fill - quote_price) * 100, 2)
        fills[amount] = fill
        slips[amount] = slip_pp
        evs[amount] = round((float(signal.p_hat) - fill) * 100, 2)

    positive_sizes = [amt for amt in SIZE_BUCKETS if evs[amt] > 0]
    min_edge_sizes = [amt for amt in SIZE_BUCKETS if evs[amt] >= float(getattr(strategy, "min_ev_pp", 0.0))]

    return ExecutionSnapshot(
        strategy=signal.strategy,
        market_id=signal.market_id,
        market_title=signal.market_title,
        outcome=signal.outcome,
        quote_price=quote_price,
        best_bid=best_bid,
        best_ask=best_ask,
        quoted_spread=spread,
        order_min_size=order_min_size,
        liquidity_proxy=liquidity_proxy,
        source_confidence=source_confidence,
        fill_price_10=fills[10.0],
        fill_price_25=fills[25.0],
        fill_price_50=fills[50.0],
        fill_price_100=fills[100.0],
        fill_price_250=fills[250.0],
        slippage_10_pp=slips[10.0],
        slippage_25_pp=slips[25.0],
        slippage_50_pp=slips[50.0],
        slippage_100_pp=slips[100.0],
        slippage_250_pp=slips[250.0],
        ev_after_slippage_10_pp=evs[10.0],
        ev_after_slippage_25_pp=evs[25.0],
        ev_after_slippage_50_pp=evs[50.0],
        ev_after_slippage_100_pp=evs[100.0],
        ev_after_slippage_250_pp=evs[250.0],
        max_size_positive_ev=max(positive_sizes) if positive_sizes else 0.0,
        max_size_above_min_edge=max(min_edge_sizes) if min_edge_sizes else 0.0,
    )

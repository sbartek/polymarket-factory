"""
Strategy: conditional_outcome_drift
Hypothesis: Conditional child markets can drift sharply even when the parent
condition barely moves. When that happens, the child is often temporarily
mispriced relative to the parent branch and mean-reverts.

This implementation uses recent market_observations:
- find explicit "If ..., ..." conditional child markets
- map them to a parent question in the same event
- compare the most recent child move vs parent move
- fade child moves when child drift is large and parent drift is muted
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..db import FactoryDB
from ..feed import event_url
from ..models import Signal
from .base import Strategy
from .conditional_outcome_count_asymmetry import _normalize_text, _parse_conditional_question

MIN_CHILD_MOVE = 0.08
MAX_PARENT_MOVE = 0.03
MIN_VOLUME = 1_000
MIN_PRICE = 0.08
MAX_PRICE = 0.92
MAX_ALERTS_PER_RUN = 3


@dataclass
class DriftCandidate:
    event_slug: str
    event_title: str
    child_market_id: str
    child_question: str
    parent_question: str
    child_cur_price: float
    child_prev_price: float
    child_move: float
    parent_cur_price: float
    parent_prev_price: float
    parent_move: float
    closes: str
    url: str


def _extract_active_market_prices(ev: dict) -> dict[str, float]:
    prices: dict[str, float] = {}
    for market in ev.get("markets", []) or []:
        if market.get("closed"):
            continue
        raw = market.get("outcomePrices") or [0]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
        try:
            prices[str(market.get("id", ""))] = float(raw[0])
        except (IndexError, ValueError, TypeError):
            continue
    return prices


def _best_parent_market(ev: dict, condition: str) -> tuple[str, str] | None:
    condition_norm = _normalize_text(condition)
    condition_tokens = set(condition_norm.split())
    if not condition_tokens:
        return None

    best: tuple[str, str] | None = None
    best_score = 0.0
    for market in ev.get("markets", []) or []:
        if market.get("closed"):
            continue
        question = str(market.get("question") or "").strip()
        if not question or question.lower().startswith("if "):
            continue
        q_tokens = set(_normalize_text(question).split())
        overlap = len(condition_tokens & q_tokens)
        score = overlap / max(len(condition_tokens), len(q_tokens) or 1)
        if overlap >= 2 and score > best_score:
            best_score = score
            best = (str(market.get("id", "")), question)
    return best


class ConditionalOutcomeDriftStrategy(Strategy):
    name = "conditional_outcome_drift"
    edge_type = "logical_inconsistency"
    time_window = "short"
    target_hold_min_days = 0.1
    target_hold_max_days = 3.0
    scan_frequency = "3x/day"
    max_position_usdc = 0.0
    min_position_usdc = 0.0
    min_ev_pp = 8.0
    alert_only = True
    trading_enabled = False
    promotable = True
    live_ready = False
    promotion_criteria = "20 alerts with >55% child move reversion within 24h"
    last_check_details: list[dict] = []

    def _candidates(self, markets: list[dict], moves_by_market: dict[str, dict]) -> list[DriftCandidate]:
        candidates: list[DriftCandidate] = []
        for ev in markets:
            market_prices = _extract_active_market_prices(ev)
            for market in ev.get("markets", []) or []:
                if market.get("closed"):
                    continue
                child_id = str(market.get("id", ""))
                child_question = str(market.get("question") or "").strip()
                parsed = _parse_conditional_question(child_question)
                if not parsed:
                    continue
                condition, _consequent = parsed
                parent_match = _best_parent_market(ev, condition)
                if not parent_match:
                    continue
                parent_id, parent_question = parent_match
                child_move = moves_by_market.get(child_id)
                parent_move = moves_by_market.get(parent_id)
                if not child_move or not parent_move:
                    continue
                if abs(child_move["price_move"]) < MIN_CHILD_MOVE:
                    continue
                if abs(parent_move["price_move"]) > MAX_PARENT_MOVE:
                    continue
                child_cur_price = float(child_move["cur_price"])
                if not (MIN_PRICE <= child_cur_price <= MAX_PRICE):
                    continue
                volume = float(child_move.get("volume") or child_move.get("volume_24hr") or 0)
                if volume < MIN_VOLUME:
                    continue
                candidates.append(
                    DriftCandidate(
                        event_slug=ev.get("slug") or "",
                        event_title=ev.get("title") or "",
                        child_market_id=child_id,
                        child_question=child_question,
                        parent_question=parent_question,
                        child_cur_price=child_cur_price,
                        child_prev_price=float(child_move["prev_price"]),
                        child_move=float(child_move["price_move"]),
                        parent_cur_price=float(parent_move["cur_price"]),
                        parent_prev_price=float(parent_move["prev_price"]),
                        parent_move=float(parent_move["price_move"]),
                        closes=(ev.get("endDate") or "")[:10],
                        url=event_url(ev),
                    )
                )
        candidates.sort(key=lambda c: abs(c.child_move - c.parent_move), reverse=True)
        return candidates

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        try:
            db = FactoryDB()
        except Exception:
            print(f"  [{self.name}] DB unavailable, 0 alerts")
            return []

        moves = db.get_recent_price_moves(min_move=MIN_CHILD_MOVE, max_hours=6.0)
        moves_by_market = {str(row["market_id"]): row for row in moves}
        candidates = self._candidates(markets, moves_by_market)

        signals: list[Signal] = []
        for c in candidates[:MAX_ALERTS_PER_RUN]:
            if c.child_move > 0:
                outcome = "NO"
                market_price = round(1.0 - c.child_cur_price, 4)
                expected_yes = min(max(c.child_prev_price + c.parent_move, 0.01), 0.99)
                p_hat = round(1.0 - expected_yes, 4)
            else:
                outcome = "YES"
                market_price = round(c.child_cur_price, 4)
                expected_yes = min(max(c.child_prev_price + c.parent_move, 0.01), 0.99)
                p_hat = round(expected_yes, 4)

            ev_pp = round((p_hat - market_price) * 100, 1)
            if ev_pp < self.min_ev_pp:
                continue

            self.last_check_details.append({
                "market_slug": c.event_slug,
                "title": c.child_question[:120],
                "parent_question": c.parent_question[:80],
                "child_move": round(c.child_move, 4),
                "parent_move": round(c.parent_move, 4),
                "decision": "alert",
                "reason": "child_drift_vs_parent",
            })

            signals.append(
                Signal(
                    strategy=self.name,
                    market_id=f"{c.event_slug}:{c.child_market_id}",
                    market_title=c.child_question[:100],
                    outcome=outcome,
                    market_price=market_price,
                    p_hat=p_hat,
                    ev_pp=ev_pp,
                    confidence="high" if abs(c.child_move - c.parent_move) >= 0.12 else "medium",
                    closes=c.closes,
                    url=c.url,
                    rationale=f"child_move={c.child_move:+.3f},parent_move={c.parent_move:+.3f},expected_yes={expected_yes:.3f}",
                )
            )

        print(f"  [{self.name}] {len(candidates)} drift candidates, {len(signals)} alerts")
        return signals

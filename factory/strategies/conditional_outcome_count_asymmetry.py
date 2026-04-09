"""
Strategy: conditional_outcome_count_asymmetry
Hypothesis: Conditional sub-markets that share the same prerequisite and split a
count/range outcome space should sum to <= 100% on the conditional branch.
If their YES prices oversum materially, the most expensive child is overpriced.

This is a narrower, real implementation of the generated proposal:
- only considers explicit "If ..., ..." conditional questions
- only considers child outcomes that look like count/range buckets
- only alerts on clear oversums across children with the same condition
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

from ..feed import event_url
from ..models import Signal
from .base import Strategy

MIN_VOLUME = 500
MIN_CHILD_PRICE = 0.03
MAX_CHILD_PRICE = 0.97
MIN_CHILDREN = 2
MIN_OVERSUM = 1.08
MAX_OVERSUM = 1.60
MIN_DAYS = 1
MAX_DAYS = 30
MAX_ALERTS_PER_RUN = 3

NON_EXCLUSIVE_KEYWORDS = ["hit", "reach", "above", "below", "at least", "at most", "more than", "less than"]


@dataclass
class ConditionalLeg:
    market_id: str
    question: str
    yes_price: float
    volume: float


@dataclass
class ConditionalOversumCandidate:
    event_slug: str
    title: str
    url: str
    closes: str
    days_to_close: int
    condition: str
    parent_question: str | None
    parent_yes_price: float | None
    legs: list[ConditionalLeg]
    total_yes: float
    oversum_pp: float
    chosen_leg: ConditionalLeg


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\bwill\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_conditional_question(question: str) -> tuple[str, str] | None:
    q = " ".join(question.strip().split())
    match = re.match(r"^if\s+(.+?)(?:,|\?)\s*(.+)$", q, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.match(r"^if\s+(.+?)\s+then\s+(.+)$", q, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None


def _looks_like_count_bucket(text: str) -> bool:
    tl = text.lower()
    if any(keyword in tl for keyword in NON_EXCLUSIVE_KEYWORDS):
        return False
    return bool(
        re.search(r"\b\d+\s*-\s*\d+\b", tl)
        or re.search(r"\b\d+\+\b", tl)
        or re.search(r"\b\d+\s+or\s+more\b", tl)
        or re.search(r"\b\d+\s+to\s+\d+\b", tl)
        or re.search(r"\bexactly\s+\d+\b", tl)
        or tl.startswith("how many ")
        or bool(re.search(r"\b(seats|states|goals|points|wins|medals|count|electoral votes)\b", tl))
    )


def _get_yes_price(market: dict) -> float | None:
    prices_raw = market.get("outcomePrices", "[]")
    try:
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        if prices:
            return float(prices[0])
    except (ValueError, TypeError, IndexError):
        return None
    return None


def _match_parent_question(markets: list[dict], condition: str) -> tuple[str | None, float | None]:
    condition_norm = _normalize_text(condition)
    condition_tokens = set(condition_norm.split())
    if not condition_tokens:
        return None, None

    best_question = None
    best_price = None
    best_score = 0.0

    for market in markets:
        if market.get("closed"):
            continue
        question = str(market.get("question") or "").strip()
        if not question or question.lower().startswith("if "):
            continue
        price = _get_yes_price(market)
        if price is None:
            continue
        question_norm = _normalize_text(question)
        question_tokens = set(question_norm.split())
        if not question_tokens:
            continue
        overlap = len(condition_tokens & question_tokens)
        score = overlap / max(len(condition_tokens), len(question_tokens))
        if score > best_score and overlap >= 2:
            best_score = score
            best_question = question
            best_price = price

    return best_question, best_price


class ConditionalOutcomeCountAsymmetryStrategy(Strategy):
    name = "conditional_outcome_count_asymmetry"
    edge_type = "logical_inconsistency"
    time_window = "short"
    target_hold_min_days = 1.0
    target_hold_max_days = 7.0
    scan_frequency = "3x/day"
    max_position_usdc = 0.0
    min_position_usdc = 0.0
    min_ev_pp = 8.0
    alert_only = True
    trading_enabled = False
    promotable = True
    live_ready = False
    promotion_criteria = "20 alerts with >60% oversum compression within 7 days"
    last_check_details: list[dict] = []

    def _candidate_from_event(self, ev: dict) -> list[ConditionalOversumCandidate]:
        title = ev.get("title") or "?"
        days = _days_to_close(ev.get("endDate"))
        if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
            return []

        event_slug = ev.get("slug", "") or str(ev.get("id", ""))
        markets = ev.get("markets", []) or []
        by_condition: dict[str, list[ConditionalLeg]] = {}

        for market in markets:
            if market.get("closed"):
                continue
            question = str(market.get("question") or "").strip()
            parsed = _parse_conditional_question(question)
            if not parsed:
                continue
            condition, consequent = parsed
            yes_price = _get_yes_price(market)
            if yes_price is None or not (MIN_CHILD_PRICE <= yes_price <= MAX_CHILD_PRICE):
                continue
            volume = float(market.get("volume") or ev.get("volume24hr") or ev.get("volume") or 0)
            if volume < MIN_VOLUME:
                continue
            if not _looks_like_count_bucket(consequent):
                continue
            by_condition.setdefault(_normalize_text(condition), []).append(
                ConditionalLeg(
                    market_id=str(market.get("id", "")),
                    question=question,
                    yes_price=yes_price,
                    volume=volume,
                )
            )

        candidates: list[ConditionalOversumCandidate] = []
        for condition_key, legs in by_condition.items():
            if len(legs) < MIN_CHILDREN:
                continue
            total_yes = sum(leg.yes_price for leg in legs)
            if total_yes < MIN_OVERSUM or total_yes > MAX_OVERSUM:
                continue
            oversum_pp = round((total_yes - 1.0) * 100, 1)
            chosen = max(legs, key=lambda leg: leg.yes_price)
            parent_question, parent_yes_price = _match_parent_question(markets, condition_key)
            candidates.append(
                ConditionalOversumCandidate(
                    event_slug=event_slug,
                    title=title,
                    url=event_url(ev),
                    closes=(ev.get("endDate") or "")[:10],
                    days_to_close=days,
                    condition=condition_key,
                    parent_question=parent_question,
                    parent_yes_price=parent_yes_price,
                    legs=legs,
                    total_yes=round(total_yes, 4),
                    oversum_pp=oversum_pp,
                    chosen_leg=chosen,
                )
            )
        return candidates

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        candidates: list[ConditionalOversumCandidate] = []
        for ev in markets:
            candidates.extend(self._candidate_from_event(ev))

        candidates.sort(key=lambda c: c.oversum_pp, reverse=True)
        selected = candidates[:MAX_ALERTS_PER_RUN]
        selected_keys = {(c.event_slug, c.condition) for c in selected}

        for c in candidates:
            self.last_check_details.append({
                "market_slug": c.event_slug,
                "title": c.title,
                "condition": c.condition,
                "leg_count": len(c.legs),
                "total_yes": c.total_yes,
                "oversum_pp": c.oversum_pp,
                "parent_question": (c.parent_question or "")[:80],
                "parent_yes_price": c.parent_yes_price,
                "decision": "alert" if (c.event_slug, c.condition) in selected_keys else "skipped",
                "reason": "top_conditional_oversum" if (c.event_slug, c.condition) in selected_keys else "below_cutoff",
            })

        signals: list[Signal] = []
        for c in selected:
            chosen = c.chosen_leg
            market_price_no = round(1.0 - chosen.yes_price, 4)
            p_hat_no = round(min(market_price_no + (c.oversum_pp / 100), 0.99), 4)
            rationale_bits = [
                f"conditional_sum={c.total_yes:.3f}",
                f"oversum={c.oversum_pp:.1f}pp",
                f"legs={len(c.legs)}",
            ]
            if c.parent_question and c.parent_yes_price is not None:
                rationale_bits.append(f"parent_yes={c.parent_yes_price:.3f}")
            signals.append(
                Signal(
                    strategy=self.name,
                    market_id=f"{c.event_slug}:{chosen.market_id}",
                    market_title=chosen.question[:100],
                    outcome="NO",
                    market_price=market_price_no,
                    p_hat=p_hat_no,
                    ev_pp=round(c.oversum_pp, 1),
                    confidence="high" if c.oversum_pp >= 15 else "medium",
                    closes=c.closes,
                    url=c.url,
                    rationale=",".join(rationale_bits),
                )
            )

        print(f"  [{self.name}] {len(signals)} alerts ({len(candidates)} candidates)")
        return signals

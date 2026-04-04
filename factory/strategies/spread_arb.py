"""
Strategy: spread_arb
Hypothesis: In multi-outcome markets the sum of all YES prices should be ~1.0.
When the sum is significantly below 1.0, buying all outcomes can lock in basket EV.
"""
import json
from dataclasses import dataclass
from datetime import date

from ..feed import event_url
from ..models import Signal
from .base import Strategy

ARB_THRESHOLD = 0.90
MIN_OUTCOMES = 3
MIN_VOLUME = 15_000
MIN_DAYS_TO_CLOSE = 7
MAX_DAYS_TO_CLOSE = 90
MAX_NEW_BASKETS_PER_RUN = 3
MIN_LEG_PRICE = 0.03
MAX_LEG_PRICE = 0.97
MIN_ACTIONABLE_SIZE = 1.0
MAX_TINY_LEGS_PER_BASKET = 2
SUSPICIOUS_OUTCOME_KEYWORDS = ["other", "none of the above", "the field", "field", "all others"]
# Title keywords that suggest a large open field where we can't enumerate all outcomes
MANY_OUTCOMES_KEYWORDS = [
    "winner", "nominee", "election", "award",
    "champion", "championship", "next to", "who will be",
]


@dataclass
class BasketCandidate:
    event_slug: str
    title: str
    url: str
    closes: str
    days_to_close: int
    volume: float
    active: list[dict]
    total_price: float
    gap_pp: float
    score: float


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


class SpreadArbStrategy(Strategy):
    name = "spread_arb"
    last_basket_details: list[dict] = []
    edge_type = "structural"
    time_window = "medium"
    target_hold_min_days = 7
    target_hold_max_days = 30
    scan_frequency = "daily"
    max_position_usdc = 8.0
    min_ev_pp = 10.0
    min_position_usdc = 1.0

    def size(self, signal: Signal) -> float:
        return round(min(self.max_position_usdc * signal.market_price * 1.35, self.max_position_usdc), 2)

    def _looks_suspicious(self, event_title: str, active: list[dict]) -> bool:
        lower_title = event_title.lower()
        likely_many_outcomes = any(k in lower_title for k in MANY_OUTCOMES_KEYWORDS)
        if not likely_many_outcomes:
            return False
        has_catch_all = any(
            any(keyword in leg["question"].lower() for keyword in SUSPICIOUS_OUTCOME_KEYWORDS)
            for leg in active
        )
        # Suspicious if no catch-all leg — we're holding a partial basket from a large field
        return not has_catch_all

    def _estimated_leg_size(self, yes_price: float) -> float:
        return round(min(self.max_position_usdc * yes_price * 1.35, self.max_position_usdc), 2)

    def _candidate_from_event(self, ev: dict) -> BasketCandidate | None:
        vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
        if vol < MIN_VOLUME:
            return None
        days = _days_to_close(ev.get("endDate"))
        if days is None or not (MIN_DAYS_TO_CLOSE <= days <= MAX_DAYS_TO_CLOSE):
            return None

        event_slug = ev.get("slug", "") or str(ev.get("id", ""))
        url = event_url(ev)
        closes = (ev.get("endDate") or "")[:10]
        title = ev.get("title") or "?"

        active = []
        tiny_legs = 0
        for m in ev.get("markets", []):
            if m.get("closed"):
                continue
            prices_raw = m.get("outcomePrices", "[]")
            try:
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                yes_price = float(prices[0])
            except (ValueError, TypeError, IndexError):
                continue
            if yes_price < MIN_LEG_PRICE or yes_price > MAX_LEG_PRICE:
                continue
            est_size = self._estimated_leg_size(yes_price)
            if est_size < MIN_ACTIONABLE_SIZE:
                tiny_legs += 1
                continue
            active.append({
                "id": str(m.get("id", "")),
                "question": (m.get("question") or title).strip(),
                "yes_price": yes_price,
                "est_size": est_size,
            })

        if len(active) < MIN_OUTCOMES or tiny_legs > MAX_TINY_LEGS_PER_BASKET or self._looks_suspicious(title, active):
            return None

        total = sum(m["yes_price"] for m in active)
        if total >= ARB_THRESHOLD:
            return None

        gap_pp = round((1.0 - total) * 100, 1)
        liquidity_weight = min(vol / 25_000, 3.0)
        time_weight = 1 / max(days ** 0.5, 1)
        deployability = min(len(active) / 5, 1.5)
        score = round(gap_pp * liquidity_weight * time_weight * deployability, 3)

        return BasketCandidate(event_slug, title, url, closes, days, vol, active, round(total, 4), gap_pp, score)

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_basket_details = []
        candidates = [c for ev in markets if (c := self._candidate_from_event(ev))]
        candidates.sort(key=lambda c: (c.score, c.gap_pp, c.volume), reverse=True)
        selected = candidates[:MAX_NEW_BASKETS_PER_RUN]
        selected_slugs = {b.event_slug for b in selected}

        for basket in candidates:
            self.last_basket_details.append({
                "event_slug": basket.event_slug,
                "title": basket.title,
                "leg_count": len(basket.active),
                "total_yes_sum": basket.total_price,
                "gap_pp": basket.gap_pp,
                "score": basket.score,
                "days_to_close": basket.days_to_close,
                "volume": basket.volume,
                "decision": "selected" if basket.event_slug in selected_slugs else "rejected",
                "reason": "top_ranked" if basket.event_slug in selected_slugs else "below_cutoff",
            })

        signals: list[Signal] = []
        for basket in selected:
            n = len(basket.active)
            print(f"  [{self.name}] basket {basket.title[:52]} | legs={n} sum={basket.total_price:.3f} gap={basket.gap_pp:.1f}pp days={basket.days_to_close} vol=${basket.volume:,.0f} score={basket.score:.3f}")
            for leg in basket.active:
                market_id = f"{basket.event_slug}:{leg['id']}"
                p_hat = leg["yes_price"] + (1.0 - basket.total_price) / n
                signals.append(Signal(
                    strategy=self.name,
                    market_id=market_id,
                    market_title=leg["question"][:100],
                    outcome="YES",
                    market_price=round(leg["yes_price"], 4),
                    p_hat=round(min(p_hat, 0.99), 4),
                    ev_pp=round(basket.gap_pp, 1),
                    confidence="high",
                    closes=basket.closes,
                    url=basket.url,
                    rationale=f"arb-basket-v3:{n}legs,sum={basket.total_price:.3f},gap={basket.gap_pp}pp,days={basket.days_to_close},score={basket.score}",
                ))

        print(f"  [{self.name}] {len(signals)} signals ({len(selected)} baskets selected from {len(candidates)} candidates)")
        return signals

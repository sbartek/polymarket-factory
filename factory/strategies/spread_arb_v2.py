"""
Strategy: spread_arb_v2
Hypothesis: In multi-outcome markets where the sum of YES prices < 1.0,
most legs will resolve NO. Bet NO on the most overpriced leg(s) —
the ones with the highest YES price that are most likely to lose.

Replaces spread_arb (v1 bet YES on all legs — 1% win rate over 79 trades).
"""
import json
from dataclasses import dataclass
from datetime import date

from ..feed import event_url
from ..models import Signal
from .base import Strategy

ARB_THRESHOLD = 0.90
MIN_OUTCOMES = 2
MIN_VOLUME = 5_000
MIN_DAYS_TO_CLOSE = 3
MAX_DAYS_TO_CLOSE = 30
MAX_NEW_BASKETS_PER_RUN = 3
MIN_LEG_YES_PRICE = 0.10  # only bet NO on legs where YES > 10c
MAX_LEG_YES_PRICE = 0.70  # avoid legs that are likely winners
MAX_LEGS_PER_BASKET = 2   # bet NO on top 1-2 overpriced legs, not all
SUSPICIOUS_OUTCOME_KEYWORDS = ["other", "none of the above", "the field", "field", "all others"]
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
    legs: list[dict]
    total_yes_sum: float
    gap_pp: float
    best_no_legs: list[dict]
    score: float


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


class SpreadArbV2Strategy(Strategy):
    name = "spread_arb_v2"
    last_basket_details: list[dict] = []
    edge_type = "structural"
    time_window = "medium"
    target_hold_min_days = 3
    target_hold_max_days = 30
    scan_frequency = "daily"
    max_position_usdc = 10.0
    min_ev_pp = 5.0
    min_position_usdc = 1.0
    alert_only = True

    def size(self, signal: Signal) -> float:
        # NO price = 1 - YES price; size based on NO entry cost
        no_price = 1.0 - signal.market_price
        return round(min(self.max_position_usdc, self.max_position_usdc * no_price * 1.5), 2)

    def _looks_suspicious(self, event_title: str, legs: list[dict]) -> bool:
        lower_title = event_title.lower()
        likely_many_outcomes = any(k in lower_title for k in MANY_OUTCOMES_KEYWORDS)
        if not likely_many_outcomes:
            return False
        has_catch_all = any(
            any(keyword in leg["question"].lower() for keyword in SUSPICIOUS_OUTCOME_KEYWORDS)
            for leg in legs
        )
        return not has_catch_all

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

        legs = []
        for m in ev.get("markets", []):
            if m.get("closed"):
                continue
            prices_raw = m.get("outcomePrices", "[]")
            try:
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                yes_price = float(prices[0])
            except (ValueError, TypeError, IndexError):
                continue
            if yes_price < 0.03 or yes_price > 0.97:
                continue
            legs.append({
                "id": str(m.get("id", "")),
                "question": (m.get("question") or title).strip(),
                "yes_price": yes_price,
            })

        if len(legs) < MIN_OUTCOMES or self._looks_suspicious(title, legs):
            return None

        total = sum(m["yes_price"] for m in legs)
        if total >= ARB_THRESHOLD:
            return None

        gap_pp = round((1.0 - total) * 100, 1)

        # Pick legs to bet NO on: highest YES price within our range
        no_candidates = [
            leg for leg in legs
            if MIN_LEG_YES_PRICE <= leg["yes_price"] <= MAX_LEG_YES_PRICE
        ]
        no_candidates.sort(key=lambda l: l["yes_price"], reverse=True)
        best_no_legs = no_candidates[:MAX_LEGS_PER_BASKET]

        if not best_no_legs:
            return None

        liquidity_weight = min(vol / 25_000, 3.0)
        time_weight = 1 / max(days ** 0.5, 1)
        # Higher YES price on target legs = cheaper NO entry = better
        avg_yes = sum(l["yes_price"] for l in best_no_legs) / len(best_no_legs)
        price_weight = avg_yes * 2  # favor legs with higher YES (cheaper NO)
        score = round(gap_pp * liquidity_weight * time_weight * price_weight, 3)

        return BasketCandidate(
            event_slug, title, url, closes, days, vol, legs,
            round(total, 4), gap_pp, best_no_legs, score,
        )

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
                "leg_count": len(basket.legs),
                "total_yes_sum": basket.total_yes_sum,
                "gap_pp": basket.gap_pp,
                "score": basket.score,
                "days_to_close": basket.days_to_close,
                "volume": basket.volume,
                "no_leg_count": len(basket.best_no_legs),
                "no_legs_avg_yes": round(
                    sum(l["yes_price"] for l in basket.best_no_legs) / len(basket.best_no_legs), 3
                ),
                "decision": "selected" if basket.event_slug in selected_slugs else "rejected",
                "reason": "top_ranked" if basket.event_slug in selected_slugs else "below_cutoff",
            })

        signals: list[Signal] = []
        for basket in selected:
            n_total = len(basket.legs)
            for leg in basket.best_no_legs:
                market_id = f"{basket.event_slug}:{leg['id']}"
                no_price = 1.0 - leg["yes_price"]
                # p_hat for NO: probability this leg resolves NO
                # With sum < 0.90, each leg's implied YES prob is inflated
                # P(NO) ≈ 1 - (yes_price - gap_share)
                gap_share = (1.0 - basket.total_yes_sum) / n_total
                p_no = 1.0 - (leg["yes_price"] - gap_share)
                ev_pp = round((p_no - no_price) * 100, 1)

                print(
                    f"  [{self.name}] NO {leg['question'][:44]} | "
                    f"yes={leg['yes_price']:.2f} no_entry={no_price:.2f} "
                    f"p_no={p_no:.3f} ev={ev_pp}pp | "
                    f"basket {n_total}legs sum={basket.total_yes_sum:.3f}"
                )
                signals.append(Signal(
                    strategy=self.name,
                    market_id=market_id,
                    market_title=leg["question"][:100],
                    outcome="NO",
                    market_price=round(leg["yes_price"], 4),
                    p_hat=round(min(p_no, 0.99), 4),
                    ev_pp=ev_pp,
                    confidence="high",
                    closes=basket.closes,
                    url=basket.url,
                    rationale=(
                        f"arb-v2:NO on overpriced leg,{n_total}legs,"
                        f"sum={basket.total_yes_sum:.3f},gap={basket.gap_pp}pp,"
                        f"days={basket.days_to_close},score={basket.score}"
                    ),
                ))

        print(f"  [{self.name}] {len(signals)} NO signals ({len(selected)} baskets from {len(candidates)} candidates)")
        return signals

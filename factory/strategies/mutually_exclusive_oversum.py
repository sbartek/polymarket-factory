"""
Strategy: mutually_exclusive_oversum
Hypothesis: When the sum of YES prices across mutually exclusive outcomes exceeds ~1.08,
            the most overpriced candidate is mathematically mispriced. Buying NO on that
            candidate exploits a provable logical inconsistency — not a probabilistic opinion.
Method: Scan multi-outcome events, compute basket sum, signal when oversum > threshold.
        Buy NO on the leg whose YES price most exceeds its fair share (1/n).
Status: ALERT-ONLY — accumulate 20 signals before enabling paper trading.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_OVERSUM = 1.08        # 8% oversum — covers ~2% fees per leg with margin
MAX_OVERSUM = 1.50        # > 150% sum almost certainly means non-exclusive legs (e.g. price targets)
MIN_LEGS = 3
MIN_VOLUME = 500          # per leg — lower bar than spread_arb, only one leg traded
MIN_DAYS = 7
MAX_DAYS = 60
MAX_ALERTS_PER_RUN = 3
MIN_LEG_PRICE = 0.03
MAX_LEG_PRICE = 0.97

# Same keyword sets as spread_arb for completeness checks
MANY_OUTCOMES_KEYWORDS = [
    "winner", "nominee", "election", "award",
    "champion", "championship", "next to", "who will be",
]
CATCH_ALL_KEYWORDS = ["other", "none of the above", "the field", "field", "all others"]
# Leg question keywords that indicate non-exclusive price target markets
# ("Will BTC hit $80k?" — multiple legs can resolve YES simultaneously)
NON_EXCLUSIVE_LEG_KEYWORDS = ["hit", "reach", "dip", "drop", "rise", "above", "below", "exceed", "surpass"]


@dataclass
class OversumCandidate:
    event_slug: str
    title: str
    url: str
    closes: str
    days_to_close: int
    legs: list[dict]   # each: {id, question, yes_price}
    total_yes: float
    oversum_pp: float
    chosen_leg: dict   # the leg to buy NO on


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _is_incomplete_field(title: str, legs: list[dict]) -> bool:
    """True if this looks like an open field without a catch-all leg — incomplete set."""
    lower = title.lower()
    if not any(k in lower for k in MANY_OUTCOMES_KEYWORDS):
        return False
    has_catch_all = any(
        any(kw in leg["question"].lower() for kw in CATCH_ALL_KEYWORDS)
        for leg in legs
    )
    return not has_catch_all


class MutuallyExclusiveOversumStrategy(Strategy):
    name = "mutually_exclusive_oversum"
    edge_type = "logical_inconsistency"
    time_window = "short"
    target_hold_min_days = 3
    target_hold_max_days = 30
    scan_frequency = "daily"
    max_position_usdc = 10.0
    min_position_usdc = 2.0
    min_ev_pp = 8.0
    alert_only = False          # promoted 2026-04-06 after 58 alerts (threshold was 20)
    trading_enabled = True
    promotable = True
    promotion_criteria = "20 alerts logged with >60% showing revert within 7 days"
    last_check_details: list[dict] = []

    def _candidate_from_event(self, ev: dict) -> OversumCandidate | None:
        title = ev.get("title") or "?"
        days = _days_to_close(ev.get("endDate"))
        if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
            return None

        event_slug = ev.get("slug", "") or str(ev.get("id", ""))

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
            if yes_price < MIN_LEG_PRICE or yes_price > MAX_LEG_PRICE:
                continue
            vol = float(m.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            legs.append({
                "id": str(m.get("id", "")),
                "question": (m.get("question") or title).strip(),
                "yes_price": yes_price,
            })

        if len(legs) < MIN_LEGS:
            return None
        if _is_incomplete_field(title, legs):
            return None
        # Reject if any leg uses price-target language — multiple legs can resolve YES simultaneously
        if any(
            any(kw in leg["question"].lower() for kw in NON_EXCLUSIVE_LEG_KEYWORDS)
            for leg in legs
        ):
            return None

        total_yes = sum(leg["yes_price"] for leg in legs)
        if total_yes < MIN_OVERSUM or total_yes > MAX_OVERSUM:
            return None

        oversum_pp = round((total_yes - 1.0) * 100, 1)

        # Choose the most overpriced leg: highest excess above fair share (1/n)
        fair_share = 1.0 / len(legs)
        chosen = max(legs, key=lambda l: l["yes_price"] - fair_share)

        return OversumCandidate(
            event_slug=event_slug,
            title=title,
            url=event_url(ev),
            closes=(ev.get("endDate") or "")[:10],
            days_to_close=days,
            legs=legs,
            total_yes=round(total_yes, 4),
            oversum_pp=oversum_pp,
            chosen_leg=chosen,
        )

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        candidates: list[OversumCandidate] = []

        for ev in markets:
            c = self._candidate_from_event(ev)
            if c:
                candidates.append(c)

        # Sort by oversum magnitude descending
        candidates.sort(key=lambda c: c.oversum_pp, reverse=True)
        selected = candidates[:MAX_ALERTS_PER_RUN]
        selected_slugs = {c.event_slug for c in selected}

        for c in candidates:
            self.last_check_details.append({
                "market_slug": c.event_slug,
                "title": c.title,
                "oversum_pp": c.oversum_pp,
                "leg_count": len(c.legs),
                "chosen_leg": c.chosen_leg["question"][:50],
                "chosen_yes_price": c.chosen_leg["yes_price"],
                "decision": "alert" if c.event_slug in selected_slugs else "skipped",
                "reason": "top_oversum" if c.event_slug in selected_slugs else "below_cutoff",
            })

        signals: list[Signal] = []
        for c in selected:
            n = len(c.legs)
            fair_share = 1.0 / n
            p_hat = 1.0 - c.chosen_leg["yes_price"]   # NO is mispriced toward 1 - yes_price
            market_price_no = round(1.0 - c.chosen_leg["yes_price"], 4)

            print(f"  [{self.name}] ALERT {c.title[:50]} | Σ={c.total_yes:.3f} (+{c.oversum_pp:.1f}pp) | NO on {c.chosen_leg['question'][:30]} (YES={c.chosen_leg['yes_price']:.2f} fair={fair_share:.2f}) days={c.days_to_close}")

            signals.append(Signal(
                strategy=self.name,
                market_id=f"{c.event_slug}:{c.chosen_leg['id']}",
                market_title=c.chosen_leg["question"][:100],
                outcome="NO",
                market_price=market_price_no,
                p_hat=round(min(p_hat + (c.oversum_pp / 100), 0.99), 4),
                ev_pp=round(c.oversum_pp, 1),
                confidence="high" if c.oversum_pp >= 15 else "medium",
                closes=c.closes,
                url=c.url,
                rationale=f"oversum:{n}legs,sum={c.total_yes:.3f},oversum={c.oversum_pp:.1f}pp,days={c.days_to_close}",
            ))

        print(f"  [{self.name}] {len(signals)} alerts ({len(candidates)} candidates)")
        return signals

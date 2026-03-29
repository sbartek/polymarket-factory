"""
Strategy: spread_arb
Hypothesis: In multi-outcome markets (elections, awards, sports) the sum of all YES
            prices should equal ~1.0 (exactly one outcome resolves). When the sum is
            significantly below 1.0 (i.e. ≥ ARB_GAP below 1.0), buying ALL outcomes
            guarantees profit regardless of which resolves.
Method: Pure mechanical — no LLM, no API calls beyond Gamma feed.
        For each qualifying event, open YES positions on every active outcome.
        Profit = 1.0 - sum(prices) per $1 invested across the basket.
Filter: min 3 outcomes, sum < ARB_THRESHOLD, min volume.
"""
import json
from datetime import date

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

ARB_THRESHOLD = 0.93   # buy basket when sum of YES prices is below this
MIN_OUTCOMES = 3       # ignore 2-outcome markets (sum always near 1.0)
MIN_VOLUME = 5_000
MIN_DAYS_TO_CLOSE = 3  # skip markets resolving too soon (slippage risk)


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


class SpreadArbStrategy(Strategy):
    name = "spread_arb"
    max_position_usdc = 8.0
    min_ev_pp = 3.0
    min_position_usdc = 1.0

    def size(self, signal: Signal) -> float:
        """For arb, size proportionally by price so the basket is balanced."""
        # fixed per-leg size — Kelly doesn't apply cleanly to basket arb
        return round(min(self.max_position_usdc * signal.market_price * 1.5, self.max_position_usdc), 2)

    def scan(self, markets: list[dict]) -> list[Signal]:
        signals = []

        for ev in markets:
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue

            days = _days_to_close(ev.get("endDate"))
            if days is not None and days < MIN_DAYS_TO_CLOSE:
                continue

            event_slug = ev.get("slug", "") or str(ev.get("id", ""))
            url = event_url(ev)
            closes = (ev.get("endDate") or "")[:10]
            title = ev.get("title") or "?"

            # Collect active sub-markets with meaningful prices
            active = []
            for m in ev.get("markets", []):
                if m.get("closed"):
                    continue
                prices_raw = m.get("outcomePrices", "[]")
                try:
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    yes_price = float(prices[0])
                except (ValueError, TypeError, IndexError):
                    continue
                if yes_price < 0.02 or yes_price > 0.98:
                    continue
                question = m.get("question") or title
                active.append({
                    "id": str(m.get("id", "")),
                    "question": question,
                    "yes_price": yes_price,
                })

            if len(active) < MIN_OUTCOMES:
                continue

            total = sum(m["yes_price"] for m in active)
            if total >= ARB_THRESHOLD:
                continue

            gap_pp = round((1.0 - total) * 100, 1)

            for m in active:
                market_id = f"{event_slug}:{m['id']}"
                n = len(active)
                # p_hat: each outcome's fair share of the guaranteed payout
                # Distributed proportionally: outcome i pays 1/n of the basket profit
                p_hat = m["yes_price"] + (1.0 - total) / n

                signals.append(Signal(
                    strategy=self.name,
                    market_id=market_id,
                    market_title=m["question"][:100],
                    outcome="YES",
                    market_price=round(m["yes_price"], 4),
                    p_hat=round(min(p_hat, 0.99), 4),
                    ev_pp=round(gap_pp, 1),
                    confidence="high",
                    closes=closes,
                    url=url,
                    rationale=f"arb-basket:{n}legs,sum={total:.3f},gap={gap_pp}pp",
                ))

        print(f"  [{self.name}] {len(signals)} signals "
              f"({len({s.market_id.split(':')[0] for s in signals})} events)")
        return signals

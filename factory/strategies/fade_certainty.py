"""
Strategy: fade_certainty
Hypothesis: Prediction markets at extremes (>93% or <7%) are systematically
            miscalibrated by ~8-12pp due to overconfidence and anchoring.
Method: Pure statistical — no API calls, no LLM. Fast and cheap.
        Scan top markets, filter by extremes + volume + time horizon,
        exclude price-oracle markets (Bitcoin above $X, etc.).
        p̂ = market_price ± FADE_AMOUNT.
Frequency: 3x/day (same as runner schedule).
"""
from datetime import date

from ..feed import get_yes_price, event_url
from ..models import Signal
from .base import Strategy

# How many pp to fade from extreme
FADE_HIGH = 10   # market at 95% → p̂ = 85%
FADE_LOW = 8     # market at 4% → p̂ = 12%

# Filters
HIGH_THRESHOLD = 0.93
LOW_THRESHOLD = 0.07
MIN_VOLUME_USD = 30_000
MIN_DAYS_TO_CLOSE = 7
MAX_DAYS_TO_CLOSE = 120

# Keywords that indicate price-oracle markets (not suitable for fading)
ORACLE_KEYWORDS = [
    "above $", "below $", "price will", "price on", "hit $",
    "above €", "trading above", "trading below", "reaches $",
]


class FadeCertaintyStrategy(Strategy):
    name = "fade_certainty"
    paused = True
    max_position_usdc = 10.0
    min_ev_pp = FADE_LOW  # minimum signal to trade
    min_position_usdc = 2.0  # fixed floor — Kelly is tiny at extremes

    def _is_oracle_market(self, title: str) -> bool:
        t = title.lower()
        return any(kw in t for kw in ORACLE_KEYWORDS)

    def _days_to_close(self, end_date: str | None) -> int | None:
        if not end_date:
            return None
        try:
            close = date.fromisoformat(end_date[:10])
            return (close - date.today()).days
        except ValueError:
            return None

    def scan(self, markets: list[dict]) -> list[Signal]:
        signals = []

        for ev in markets:
            price = get_yes_price(ev)
            if price is None:
                continue

            # Skip anything not at an extreme
            if LOW_THRESHOLD <= price <= HIGH_THRESHOLD:
                continue

            title = ev.get("title") or ""
            if self._is_oracle_market(title):
                continue

            # Volume filter
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME_USD:
                continue

            # Time-to-close filter
            days = self._days_to_close(ev.get("endDate"))
            if days is None or not (MIN_DAYS_TO_CLOSE <= days <= MAX_DAYS_TO_CLOSE):
                continue

            slug = ev.get("slug", "") or str(ev.get("id", ""))
            url = event_url(ev)
            closes = (ev.get("endDate") or "")[:10]

            if price > HIGH_THRESHOLD:
                # Fade over-certainty: YES is overpriced → buy NO
                p_hat_yes = price - FADE_HIGH / 100
                ev_pp = (price - p_hat_yes) * 100   # positive EV on NO
                signals.append(Signal(
                    strategy=self.name,
                    market_id=slug,
                    market_title=title,
                    outcome="NO",
                    market_price=round(1 - price, 4),   # price of NO token
                    p_hat=round(1 - p_hat_yes, 4),       # prob of NO
                    ev_pp=round(ev_pp, 1),
                    confidence="medium",
                    closes=closes,
                    url=url,
                    rationale=f"fade-high:{price*100:.0f}%→est {p_hat_yes*100:.0f}%",
                ))

            elif price < LOW_THRESHOLD:
                # Fade under-certainty: YES is underpriced → buy YES
                p_hat_yes = price + FADE_LOW / 100
                ev_pp = (p_hat_yes - price) * 100
                signals.append(Signal(
                    strategy=self.name,
                    market_id=slug,
                    market_title=title,
                    outcome="YES",
                    market_price=round(price, 4),
                    p_hat=round(p_hat_yes, 4),
                    ev_pp=round(ev_pp, 1),
                    confidence="low",
                    closes=closes,
                    url=url,
                    rationale=f"fade-low:{price*100:.0f}%→est {p_hat_yes*100:.0f}%",
                ))

        print(f"  [{self.name}] {len(signals)} signals from {len(markets)} markets")
        return signals

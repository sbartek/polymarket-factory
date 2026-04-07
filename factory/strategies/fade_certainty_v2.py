"""
Strategy: fade_certainty_v2
Hypothesis: Binary prediction markets at extremes (>95% or <5%) can be
            systematically miscalibrated due to overconfidence and anchoring.
Fixes over v1:
  - Only trade BINARY markets (single-market events with YES/NO resolution)
  - Exclude sports, elections, tournaments, multi-outcome events
  - Operate at sub-market level (market_id = slug:market_id)
  - Tighter extremes (95%/5% vs 93%/7%)
Method: Pure statistical — no API calls, no LLM. Fast and cheap.
Status: ALERT-ONLY — accumulate 20 signals before enabling paper trading.
"""
import json
from datetime import date

from ..feed import event_url
from ..models import Signal
from .base import Strategy

# How many pp to fade from extreme
FADE_HIGH = 8    # market at 96% → p̂ = 88%
FADE_LOW = 8     # market at 4% → p̂ = 12%

# Filters
HIGH_THRESHOLD = 0.95
LOW_THRESHOLD = 0.05
MIN_VOLUME_USD = 50_000
MIN_DAYS_TO_CLOSE = 7
MAX_DAYS_TO_CLOSE = 90
MAX_ALERTS_PER_RUN = 3

# Markets unsuitable for fading
ORACLE_KEYWORDS = [
    "above $", "below $", "price will", "price on", "hit $",
    "above €", "trading above", "trading below", "reaches $",
    "dip to", "rise to",
]
SPORTS_KEYWORDS = [
    " vs ", " vs. ", "nba", "nhl", "nfl", "mlb", "mls",
    "premier league", "champions league", "serie a", "la liga",
    "ipl", "cricket", "tennis", "atp", "wta", "grand prix",
    "ufc", "boxing", "esport", "league of legends", "dota",
]
MULTI_OUTCOME_KEYWORDS = [
    "winner", "nominee", "election", "award", "champion",
    "championship", "next to", "who will be", "mvp",
    "most votes", "first to",
]


class FadeCertaintyV2Strategy(Strategy):
    name = "fade_certainty_v2"
    edge_type = "statistical_fade"
    time_window = "medium"
    target_hold_min_days = 7
    target_hold_max_days = 60
    scan_frequency = "3x/day"
    max_position_usdc = 8.0
    min_ev_pp = FADE_LOW
    alert_only = True
    promotable = True
    promotion_criteria = "20 alerts with >50% directional accuracy"
    signal_cooldown_hours = 72.0  # tail-event markets move slowly; daily re-fire adds no value
    last_check_details: list[dict] = []

    def _is_excluded(self, title: str) -> bool:
        t = title.lower()
        if any(kw in t for kw in ORACLE_KEYWORDS):
            return True
        if any(kw in t for kw in SPORTS_KEYWORDS):
            return True
        if any(kw in t for kw in MULTI_OUTCOME_KEYWORDS):
            return True
        return False

    def _is_binary_event(self, ev: dict) -> bool:
        """Only trade events with exactly 1 active market (binary YES/NO)."""
        active = [m for m in (ev.get("markets") or []) if not m.get("closed")]
        return len(active) == 1

    def _days_to_close(self, end_date: str | None) -> int | None:
        if not end_date:
            return None
        try:
            return (date.fromisoformat(end_date[:10]) - date.today()).days
        except ValueError:
            return None

    def _parse_yes_price(self, market: dict) -> float | None:
        prices_raw = market.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            return float(prices[0]) if prices else None
        except (ValueError, TypeError, IndexError):
            return None

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        signals = []

        for ev in markets:
            title = ev.get("title") or ""
            if self._is_excluded(title):
                continue
            if not self._is_binary_event(ev):
                continue

            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME_USD:
                continue

            days = self._days_to_close(ev.get("endDate"))
            if days is None or not (MIN_DAYS_TO_CLOSE <= days <= MAX_DAYS_TO_CLOSE):
                continue

            market = [m for m in (ev.get("markets") or []) if not m.get("closed")][0]
            price = self._parse_yes_price(market)
            if price is None:
                continue

            if LOW_THRESHOLD <= price <= HIGH_THRESHOLD:
                continue

            slug = ev.get("slug", "") or str(ev.get("id", ""))
            market_id_str = str(market.get("id", ""))
            full_market_id = f"{slug}:{market_id_str}" if market_id_str else slug
            url = event_url(ev)
            closes = (ev.get("endDate") or "")[:10]
            question = market.get("question") or title

            if price > HIGH_THRESHOLD:
                p_hat_yes = price - FADE_HIGH / 100
                ev_pp = (price - p_hat_yes) * 100
                outcome = "NO"
                mp = round(1 - price, 4)
                ph = round(1 - p_hat_yes, 4)
                rationale = f"fade-high:{price*100:.0f}%→est {p_hat_yes*100:.0f}%"
            else:
                p_hat_yes = price + FADE_LOW / 100
                ev_pp = (p_hat_yes - price) * 100
                outcome = "YES"
                mp = round(price, 4)
                ph = round(p_hat_yes, 4)
                rationale = f"fade-low:{price*100:.0f}%→est {p_hat_yes*100:.0f}%"

            self.last_check_details.append({
                "market_slug": slug,
                "title": question[:80],
                "yes_price": price,
                "outcome": outcome,
                "ev_pp": round(ev_pp, 1),
                "days_to_close": days,
                "decision": "alert",
                "reason": rationale,
            })

            signals.append(Signal(
                strategy=self.name,
                market_id=full_market_id,
                market_title=question[:100],
                outcome=outcome,
                market_price=mp,
                p_hat=ph,
                ev_pp=round(ev_pp, 1),
                confidence="medium",
                closes=closes,
                url=url,
                rationale=rationale,
            ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]

        print(f"  [{self.name}] {len(signals)} alerts from {len(markets)} markets")
        return signals

"""
Strategy: weather_oversum
Hypothesis: Temperature bin markets for a city/day must sum to 100% (exactly one
resolves YES). When the sum > 100%, bet NO on the most overpriced bins.

Pure structural arbitrage — no forecast model needed. Same logic as
mutually_exclusive_oversum but specialized for weather temperature bins.
"""
import json
from datetime import date

from ..feed import event_url, fetch_by_tag
from ..models import Signal
from .base import Strategy

MIN_BINS = 3
MIN_OVERSUM_PP = 3.0     # only signal if sum exceeds 100% by ≥3pp
MAX_DAYS_TO_CLOSE = 3    # short-term only
MIN_BIN_YES_PRICE = 0.08 # don't bet NO on bins already near 0
MAX_ALERTS_PER_RUN = 6

WEATHER_KEYWORDS = ["highest temperature", "lowest temperature", "temperature"]


def _is_weather_event(title: str) -> bool:
    return any(kw in title.lower() for kw in WEATHER_KEYWORDS)


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


class WeatherOversumStrategy(Strategy):
    name = "weather_oversum"
    edge_type = "logical_inconsistency"
    time_window = "super_short"
    target_hold_min_days = 0.02
    target_hold_max_days = 3
    scan_frequency = "3x/day"
    max_position_usdc = 5.0
    min_ev_pp = 3.0
    alert_only = True

    def scan(self, markets: list[dict]) -> list[Signal]:
        weather_events = []
        try:
            weather_events = fetch_by_tag("weather", limit=50)
        except Exception:
            pass

        seen: set[str] = set()
        all_events = []
        for ev in markets + weather_events:
            slug = ev.get("slug") or str(ev.get("id", ""))
            if slug not in seen:
                seen.add(slug)
                all_events.append(ev)

        signals: list[Signal] = []

        for ev in all_events:
            title = ev.get("title") or ""
            if not _is_weather_event(title):
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or days < 0 or days > MAX_DAYS_TO_CLOSE:
                continue

            slug = ev.get("slug", "") or str(ev.get("id", ""))
            url = event_url(ev)
            closes = (ev.get("endDate") or "")[:10]

            bins = []
            for m in ev.get("markets", []):
                if m.get("closed"):
                    continue
                prices_raw = m.get("outcomePrices", "[]")
                try:
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    yes_price = float(prices[0])
                except (ValueError, TypeError, IndexError):
                    continue
                bins.append({
                    "id": str(m.get("id", "")),
                    "question": (m.get("question") or "?").strip(),
                    "yes_price": yes_price,
                })

            if len(bins) < MIN_BINS:
                continue

            yes_sum = sum(b["yes_price"] for b in bins)
            oversum_pp = round((yes_sum - 1.0) * 100, 1)

            if oversum_pp < MIN_OVERSUM_PP:
                continue

            # Bet NO on most overpriced bins that are worth targeting
            no_targets = [b for b in bins if b["yes_price"] >= MIN_BIN_YES_PRICE]
            no_targets.sort(key=lambda b: b["yes_price"], reverse=True)

            # Take top 1-2 bins — the ones contributing most to oversum
            for b in no_targets[:2]:
                fair_yes = b["yes_price"] - (oversum_pp / 100) / len(bins)
                fair_no = 1.0 - fair_yes
                no_price = 1.0 - b["yes_price"]
                ev_pp = round((fair_no - no_price) * 100, 1)

                if ev_pp < self.min_ev_pp:
                    continue

                signals.append(Signal(
                    strategy=self.name,
                    market_id=f"{slug}:{b['id']}",
                    market_title=b["question"][:100],
                    outcome="NO",
                    market_price=round(b["yes_price"], 4),
                    p_hat=round(min(fair_no, 0.99), 4),
                    ev_pp=ev_pp,
                    confidence="high" if oversum_pp >= 5 else "medium",
                    closes=closes,
                    url=url,
                    rationale=f"weather-oversum:{len(bins)}bins,sum={yes_sum:.3f},+{oversum_pp}pp,days={days}",
                ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

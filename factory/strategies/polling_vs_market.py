"""
Strategy: polling_vs_market
Hypothesis: Polling aggregates contain information not yet fully priced into prediction markets.
Method: Filter political/approval markets from the top feed, search for recent polling data
        via DDGS, use Claude to extract a polling-implied probability, and signal when the
        gap to the market price exceeds MIN_GAP_PP.
Frequency: daily (polls don't move fast enough to warrant 3x/day)
"""
import json
import re
from datetime import date

from ddgs import DDGS

from ..claude import call_claude
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_VOLUME = 5_000
MIN_DAYS = 5
MAX_DAYS = 180
MIN_PRICE = 0.05
MAX_PRICE = 0.95
MIN_GAP_PP = 10.0
MAX_TRADES_PER_RUN = 2
MAX_CANDIDATES = 12

# Markets that are likely to have polling data
POLLING_KEYWORDS = [
    "approval", "approve", "disapprove", "disapproval",
    "election", "win", "senate", "house", "congress",
    "vote", "ballot", "primary", "candidate",
    "republican", "democrat", "gop", "dnc",
    "trump", "harris", "biden", "musk",
    "poll", "polling",
    "majority", "control",
    "gubernatorial", "governor",
    "midterm", "presidency", "president",
    "popular vote",
]


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _fetch_news(query: str, n: int = 5) -> list[dict]:
    try:
        return list(DDGS().news(query, max_results=n))
    except Exception:
        return []


def _news_to_text(news: list[dict]) -> str:
    lines = []
    for item in news:
        d = item.get("date", "")[:10]
        t = item.get("title", "?")
        b = (item.get("body") or "")[:200]
        source = item.get("source", "")
        lines.append(f"  [{d}] {t} ({source})\n  {b}")
    return "\n".join(lines) if lines else "  (no data found)"


class PollingVsMarketStrategy(Strategy):
    name = "polling_vs_market"
    edge_type = "model_vs_market"
    time_window = "medium"
    target_hold_min_days = 7
    target_hold_max_days = 60
    scan_frequency = "daily"
    max_position_usdc = 10.0
    min_ev_pp = MIN_GAP_PP
    min_position_usdc = 2.0
    last_check_details: list[dict] = []

    def _is_pollable(self, title: str) -> bool:
        tl = title.lower()
        return any(k in tl for k in POLLING_KEYWORDS)

    def _analyze_market(self, ev: dict, yes_price: float) -> dict | None:
        title = ev.get("title") or "?"
        closes = (ev.get("endDate") or "")[:10]

        # Targeted polling search: title + "poll average" and a broader one
        polls_news = _fetch_news(f"{title} polling average", n=5)
        if not polls_news:
            polls_news = _fetch_news(f"{title} poll survey", n=4)
        if not polls_news:
            return None

        prompt = f"""You are a prediction market analyst comparing polling data to a Polymarket price.

MARKET: {title}
CURRENT POLYMARKET PRICE: {yes_price * 100:.1f}% YES
CLOSES: {closes}

RECENT POLLING / SURVEY RESULTS:
{_news_to_text(polls_news)}

Instructions:
1. Find the most relevant, concrete polling number (%, approval, vote share, etc.) from the news above.
2. Convert it to a probability estimate for the YES outcome of this specific market.
   - For approval markets: poll approval % ≈ p_hat YES
   - For win/majority markets: use the polling lead and context to estimate win probability
3. Only return a signal if:
   a. You found a specific, recent poll number (not just vague sentiment)
   b. The gap between polling-implied probability and the market price is >= {MIN_GAP_PP:.0f}pp
4. If conditions not met, return <signal>null</signal>

Return JSON inside <signal> tags:
{{
  "outcome": "YES or NO",
  "market_price_pct": <integer 0-100>,
  "polling_p_hat_pct": <integer 0-100>,
  "ev_pp": <positive integer — absolute gap>,
  "confidence": "low|medium|high",
  "poll_source": "<polling firm or aggregator name>",
  "rationale": "<one sentence: what the poll says vs the market price>"
}}

<signal>null</signal>"""

        response = call_claude(prompt, max_tokens=600)
        match = re.search(r"<signal>(.*?)</signal>", response, re.DOTALL)
        if not match:
            return None
        raw = match.group(1).strip()
        if raw.lower() == "null":
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []

        candidates = []
        for ev in markets:
            title = ev.get("title") or "?"
            if not self._is_pollable(title):
                continue
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
                continue
            yes_price = get_yes_price(ev)
            if yes_price is None or not (MIN_PRICE <= yes_price <= MAX_PRICE):
                continue
            candidates.append((ev, yes_price))

        candidates = candidates[:MAX_CANDIDATES]
        print(f"  [{self.name}] {len(candidates)} pollable candidates")

        signals: list[Signal] = []
        for ev, yes_price in candidates:
            if len(signals) >= MAX_TRADES_PER_RUN:
                break

            title = ev.get("title") or "?"
            slug = ev.get("slug", "") or str(ev.get("id", ""))
            result = self._analyze_market(ev, yes_price)

            if result is None:
                self.last_check_details.append({
                    "market_slug": slug,
                    "title": title,
                    "decision": "skipped",
                    "reason": "no_polling_data_or_gap_too_small",
                })
                continue

            ev_pp = float(result.get("ev_pp", 0))
            if ev_pp < self.min_ev_pp:
                self.last_check_details.append({
                    "market_slug": slug,
                    "title": title,
                    "decision": "skipped",
                    "reason": f"gap_too_small:{ev_pp:.1f}pp",
                })
                continue

            confidence = (result.get("confidence") or "low").lower()
            outcome = (result.get("outcome") or "YES").upper()
            mp_pct = float(result.get("market_price_pct", yes_price * 100))
            ph_pct = float(result.get("polling_p_hat_pct", 50))
            mp = (100 - mp_pct) / 100 if outcome == "NO" else mp_pct / 100
            ph = (100 - ph_pct) / 100 if outcome == "NO" else ph_pct / 100

            source = (result.get("poll_source") or "?")[:50]
            rationale = (result.get("rationale") or "?")[:100]

            self.last_check_details.append({
                "market_slug": slug,
                "title": title,
                "decision": "signal",
                "reason": f"gap={ev_pp:.1f}pp,source={source}",
            })
            print(f"  [{self.name}] signal: {title[:60]} | {outcome} | poll={ph_pct:.0f}% mkt={mp_pct:.0f}% gap={ev_pp:.0f}pp ({source})")

            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=title[:100],
                outcome=outcome,
                market_price=round(mp, 4),
                p_hat=round(ph, 4),
                ev_pp=round(ev_pp, 1),
                confidence=confidence,
                closes=(ev.get("endDate") or "")[:10],
                url=event_url(ev),
                rationale=f"poll:{source}|{rationale}",
            ))

        print(f"  [{self.name}] {len(signals)} signals")
        return signals

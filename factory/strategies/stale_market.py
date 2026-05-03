"""
Strategy: stale_market
Hypothesis: Some markets lag relevant news and do not reprice quickly enough.
Method: Filter for liquid, near/medium-term markets with non-extreme prices, fetch
        recent news, and use Claude to judge whether the market appears stale versus
        the information flow. Keep trade count low and dedupe by topic cluster.
"""
import json
import re
import signal as _signal
from datetime import date

from ddgs import DDGS

from ..claude import call_claude
from ..feed import event_url, get_yes_price, markets_to_text
from ..models import Signal
from .base import Strategy

DDGS_HARD_TIMEOUT = 30

MIN_DAYS = 3
MAX_DAYS = 21
MIN_VOLUME = 8_000
MIN_PRICE = 0.10
MAX_PRICE = 0.85
MAX_CANDIDATES = 12
MAX_TRADES_PER_RUN = 2
TOPIC_KEYWORDS = [
    "trump", "fed", "iran", "israel", "gaza", "election", "tariff", "bitcoin",
    "sec", "war", "ukraine", "china", "musk", "netanyahu", "oil", "ceasefire",
]


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _fetch_news(query: str, n: int = 4) -> list[dict]:
    def _handler(signum, frame):
        raise TimeoutError(f"DDGS hung after {DDGS_HARD_TIMEOUT}s")
    try:
        old = _signal.signal(_signal.SIGALRM, _handler)
        _signal.alarm(DDGS_HARD_TIMEOUT)
        try:
            return list(DDGS(timeout=15).news(query, max_results=n))
        finally:
            _signal.alarm(0)
            _signal.signal(_signal.SIGALRM, old)
    except Exception:
        return []


def _news_to_text(news: list[dict]) -> str:
    lines = []
    for item in news:
        d = item.get("date", "")[:10]
        t = item.get("title", "?")
        b = (item.get("body") or "")[:160]
        source = item.get("source", "")
        lines.append(f"  [{d}] {t} ({source})\n  {b}")
    return "\n".join(lines) if lines else "  (no recent news found)"


def _topic_key(title: str) -> str:
    tl = title.lower()
    for k in TOPIC_KEYWORDS:
        if k in tl:
            return k
    words = re.findall(r"[a-zA-Z]{5,}", tl)
    return words[0] if words else tl[:24]


class StaleMarketStrategy(Strategy):
    name = "stale_market"
    last_check_details: list[dict] = []
    edge_type = "stale_repricing"
    time_window = "short"
    target_hold_min_days = 0.5
    target_hold_max_days = 7
    scan_frequency = "3x/day"
    max_position_usdc = 5.0   # conservative for live — was 12 for paper
    min_ev_pp = 12.0
    min_position_usdc = 2.0
    mode = "paper_and_live"
    live_ready = False  # demoted 2026-05-03: 2W/8L live, -$8.74
    fast_dry_run_candidates = 4

    def _candidate_score(self, ev: dict, days: int, price: float, news_count: int) -> float:
        vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
        title = (ev.get("title") or "").lower()
        score = 0.0
        score += min(vol / 20_000, 3.0)
        score += min(news_count, 4) * 0.7
        score += 1.5 / max(days, 1)
        score += 1.0 - abs(price - 0.5)
        if any(k in title for k in TOPIC_KEYWORDS):
            score += 1.0
        return score

    def _judge_candidates(self, candidates: list[dict]) -> list[dict]:
        candidate_text = "\n".join(
            f"[{i+1}] slug={c['slug']} | price={c['yes_price']*100:.0f}% YES | closes={c['closes']}\n"
            f"Title: {c['title']}\nRecent news:\n{_news_to_text(c['news'])}"
            for i, c in enumerate(candidates)
        )
        prompt = f"""You are evaluating whether Polymarket prices look stale versus recent news.

For each candidate below:
- read the market title and current YES price
- read the recent news
- decide if the market appears underreacted or stale
- only keep candidates where the directional edge is reasonably clear and material

Return JSON inside <signals> tags. Include ONLY candidates where |ev_pp| >= {self.min_ev_pp}.
Each object:
{{
  "slug": "<event slug>",
  "title": "<market title>",
  "outcome": "YES or NO",
  "market_price": <integer 0-100>,
  "p_hat": <integer 0-100>,
  "ev_pp": <signed integer>,
  "confidence": "low|medium|high",
  "reason": "one short sentence"
}}

CANDIDATES:
{"="*60}
{candidate_text}
{"="*60}

<signals>[]</signals>"""

        response = call_claude(prompt, max_tokens=1400)
        match = re.search(r"<signals>(.*?)</signals>", response, re.DOTALL)
        if not match:
            return []
        try:
            raw = json.loads(match.group(1).strip())
            return [r for r in raw if isinstance(r, dict)]
        except (json.JSONDecodeError, TypeError):
            return []

    def scan(self, markets: list[dict]) -> list[Signal]:
        candidates = []
        for ev in markets:
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
                continue
            price = get_yes_price(ev)
            if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                continue

            title = ev.get("title") or "?"
            news = _fetch_news(title, n=4)
            if len(news) < 2:
                continue

            candidate_score = self._candidate_score(ev, days, price, len(news))
            topic = _topic_key(title)
            candidates.append({
                "slug": ev.get("slug", "") or str(ev.get("id", "")),
                "title": title,
                "yes_price": price,
                "closes": (ev.get("endDate") or "")[:10],
                "url": event_url(ev),
                "topic": topic,
                "score": candidate_score,
                "news": news,
            })
            self.last_check_details.append({
                "market_slug": ev.get("slug", "") or str(ev.get("id", "")),
                "title": title,
                "topic_key": topic,
                "candidate_score": candidate_score,
                "news_count": len(news),
                "decision": "candidate",
                "reason": "ranked_for_judgment",
            })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        limit_candidates = getattr(self, "_fast_dry_run_candidates_override", MAX_CANDIDATES)
        candidates = candidates[:limit_candidates]
        print(f"  [{self.name}] {len(candidates)} ranked candidates → checking stale repricing...")
        if not candidates:
            print(f"  [{self.name}] 0 signals")
            return []

        judged = self._judge_candidates(candidates)
        candidate_map = {c["slug"]: c for c in candidates}
        seen_topics = set()
        signals = []
        for item in judged:
            slug = item.get("slug", "")
            c = candidate_map.get(slug)
            if not c:
                continue

            topic = c["topic"]
            if topic in seen_topics:
                continue

            confidence = (item.get("confidence", "medium") or "medium").lower()
            if confidence not in ("medium", "high"):
                continue

            ev_pp = float(item.get("ev_pp", 0))
            if abs(ev_pp) < self.min_ev_pp:
                continue

            outcome = (item.get("outcome", "YES") or "YES").upper()
            mp_pct = float(item.get("market_price", round(c["yes_price"] * 100)))
            ph_pct = float(item.get("p_hat", 50))
            mp = (100 - mp_pct) / 100 if outcome == "NO" else mp_pct / 100
            ph = (100 - ph_pct) / 100 if outcome == "NO" else ph_pct / 100

            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=c["title"][:100],
                outcome=outcome,
                market_price=round(mp, 4),
                p_hat=round(ph, 4),
                ev_pp=round(abs(ev_pp), 1),
                confidence=confidence,
                closes=c["closes"],
                url=c["url"],
                rationale=f"stale:{item.get('reason','?')[:80]}",
            ))
            seen_topics.add(topic)
            if len(signals) >= MAX_TRADES_PER_RUN:
                break

        print(f"  [{self.name}] {len(signals)} signals")
        return signals

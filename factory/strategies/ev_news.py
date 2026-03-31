"""
Strategy: ev_news
Hypothesis: Recent news contains information not yet priced into prediction markets.
Method: Use Claude to scan top markets + headlines, identify topics with likely EV,
        then estimate p̂ per market from news snippets.
Frequency: 3x/day (same as runner schedule).
"""
import json
import re
from datetime import date

from ddgs import DDGS

from ..claude import call_claude
from ..feed import fetch_by_tag, format_date, format_volume, event_url, get_yes_price, markets_to_text
from ..models import Signal
from .base import Strategy


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


class EvNewsStrategy(Strategy):
    name = "ev_news"
    edge_type = "information"
    time_window = "medium"
    target_hold_min_days = 7
    target_hold_max_days = 30
    scan_frequency = "3x/day"
    max_position_usdc = 15.0
    min_ev_pp = 10.0
    n_topics = 3
    min_volume = 10_000
    min_days_to_close = 7
    max_days_to_close = 60
    max_trades_per_run = 3
    fast_dry_run_topics = 1

    def _fetch_news(self, query: str, n: int = 5) -> list[dict]:
        try:
            return list(DDGS().news(query, max_results=n))
        except Exception:
            return []

    def _news_to_text(self, news: list[dict]) -> str:
        lines = []
        for item in news:
            date = item.get("date", "")[:10]
            title = item.get("title", "?")
            body = (item.get("body") or "")[:150]
            source = item.get("source", "")
            lines.append(f"  [{date}] {title} ({source})\n  {body}")
        return "\n".join(lines)

    def _pick_topics(self, markets: list[dict]) -> list[str]:
        broad_news = self._fetch_news("world news politics economy finance", n=10)
        prompt = f"""From these Polymarket markets and today's news, pick the {self.n_topics} topics most likely to have a news-based mispricing right now.

MARKETS (top by volume):
{markets_to_text(markets[:20])}

TODAY'S NEWS:
{self._news_to_text(broad_news)}

Return ONLY a JSON array of {self.n_topics} single lowercase words that work as Polymarket tag slugs.
Example: ["iran","fed","bitcoin"]"""

        response = call_claude(prompt)
        match = re.search(r'\[.*?\]', response, re.DOTALL)
        if match:
            try:
                return [str(q) for q in json.loads(match.group())[:self.n_topics]]
            except (json.JSONDecodeError, TypeError):
                pass
        return ["iran", "fed", "bitcoin"]

    def _analyze_topic(self, query: str, markets: list[dict]) -> list[Signal]:
        # Find relevant markets
        slug_words = query.replace("-", " ").split()
        topic_markets = fetch_by_tag(query, limit=5)
        if not topic_markets:
            topic_markets = [
                m for m in markets
                if any(w in (m.get("title") or "").lower() for w in slug_words)
            ][:5]
        if not topic_markets:
            return []

        news = self._fetch_news(query, n=5)

        prompt = f"""You are a prediction market analyst. Find mispricings for "{query}".

MARKETS:
{markets_to_text(topic_markets)}

NEWS:
{self._news_to_text(news)}

For each market where |EV| > {self.min_ev_pp}pp, estimate p̂ from the news and compute EV = p̂ – market_price.

Return a JSON array inside <signals> tags. Each object:
{{
  "slug": "<event slug from the slug= field above>",
  "title": "<market title>",
  "outcome": "YES or NO",
  "market_price": <integer 0-100>,
  "p_hat": <integer 0-100>,
  "ev_pp": <signed integer>,
  "confidence": "low|medium|high",
  "closes": "YYYY-MM-DD or null",
  "url": "<url>"
}}
Only include markets where |ev_pp| >= {self.min_ev_pp}. Return <signals>[]</signals> if none."""

        response = call_claude(prompt)
        match = re.search(r'<signals>(.*?)</signals>', response, re.DOTALL)
        if not match:
            return []

        signals = []
        try:
            raw = json.loads(match.group(1).strip())
            for s in raw:
                ev_pp = float(s.get("ev_pp", 0))
                if abs(ev_pp) < self.min_ev_pp:
                    continue

                confidence = (s.get("confidence", "medium") or "medium").lower()
                if confidence not in ("medium", "high"):
                    continue

                closes = s.get("closes") or ""
                days = _days_to_close(closes)
                if days is None or not (self.min_days_to_close <= days <= self.max_days_to_close):
                    continue

                outcome = s.get("outcome", "YES").upper()
                mp_pct = float(s.get("market_price", 50))
                ph_pct = float(s.get("p_hat", 50))
                # Normalize to price of the stated outcome
                mp = (100 - mp_pct) / 100 if outcome == "NO" else mp_pct / 100
                ph = (100 - ph_pct) / 100 if outcome == "NO" else ph_pct / 100
                signals.append(Signal(
                    strategy=self.name,
                    market_id=s.get("slug", ""),
                    market_title=s.get("title", "?"),
                    outcome=outcome,
                    market_price=mp,
                    p_hat=ph,
                    ev_pp=abs(ev_pp),
                    confidence=confidence,
                    closes=closes,
                    url=s.get("url", ""),
                    rationale=f"news-ev:{query}",
                ))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        return signals

    def scan(self, markets: list[dict]) -> list[Signal]:
        filtered_markets = []
        for m in markets:
            vol = float(m.get("volume24hr") or m.get("volume") or 0)
            if vol < self.min_volume:
                continue
            days = _days_to_close(m.get("endDate"))
            if days is None or not (self.min_days_to_close <= days <= self.max_days_to_close):
                continue
            filtered_markets.append(m)

        print(f"  [{self.name}] {len(filtered_markets)} filtered markets → picking topics...", end=" ", flush=True)
        topics = self._pick_topics(filtered_markets or markets)
        limit_topics = getattr(self, "_fast_dry_run_topics_override", None)
        if limit_topics is not None:
            topics = topics[:limit_topics]
        print(f"{topics}")

        signals = []
        seen_market_ids: set[str] = set()
        for topic in topics:
            print(f"  [{self.name}] analyzing '{topic}'...", end=" ", flush=True)
            found = self._analyze_topic(topic, filtered_markets or markets)
            kept = []
            for sig in found:
                if sig.market_id in seen_market_ids:
                    continue
                seen_market_ids.add(sig.market_id)
                kept.append(sig)
            print(f"{len(kept)} signals")
            signals.extend(kept)
            if len(signals) >= self.max_trades_per_run:
                break

        return signals[:self.max_trades_per_run]

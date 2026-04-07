"""
Strategy: resolution_hunter_v2
Hypothesis: Some prediction markets remain mispriced after the underlying event has
            resolved, especially obscure political/regulatory events where resolution
            is ambiguous and news takes time to propagate.
Fixes over v1:
  - Exclude ALL sports, weather, price-oracle, and esport markets
  - Only target political, regulatory, diplomatic, and policy events
  - Require MIN_DAYS >= 1 (no same-day events — CLOB reprices within minutes)
  - Operate at sub-market level for multi-outcome events
  - Lower batch size for more focused LLM calls
Method: DuckDuckGo news + Claude assessment of resolution status.
Status: ALERT-ONLY — accumulate 20 signals before enabling paper trading.
"""
import json
import re
from datetime import date

from ddgs import DDGS

from ..claude import call_claude
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MAX_DAYS = 30
MIN_DAYS = 1          # v1 was 0 — same-day events resolve too fast
MIN_PRICE = 0.10
MAX_PRICE = 0.85
MIN_VOLUME = 10_000   # higher than v1 — focus on liquid markets
BATCH_SIZE = 4        # smaller batches for focused Claude assessment
MAX_CANDIDATES = 10
MAX_ALERTS_PER_RUN = 3

# Only target these kinds of events
POLITICAL_KEYWORDS = [
    "trump", "biden", "congress", "senate", "house", "legislation", "bill",
    "fed", "federal reserve", "rate cut", "rate hike", "interest rate",
    "tariff", "sanction", "embargo", "trade war", "trade deal",
    "ceasefire", "peace deal", "treaty", "diplomatic", "summit",
    "election", "referendum", "vote", "resign", "impeach",
    "sec", "fda", "epa", "approval", "regulate", "ban",
    "iran", "israel", "gaza", "ukraine", "russia", "nato", "eu",
    "indictment", "trial", "verdict", "ruling", "supreme court",
]

# Exclude these entirely
EXCLUDED_KEYWORDS = [
    " vs ", " vs. ", "nba", "nhl", "nfl", "mlb", "mls", "ipl",
    "cricket", "tennis", "atp", "wta", "ufc", "boxing", "esport",
    "league of legends", "dota", "temperature", "weather", "°f", "°c",
    "above $", "below $", "price will", "hit $", "trading above",
    "bitcoin price", "ethereum price", "highest temp", "lowest temp",
    "grand prix", "premier league", "champions league",
]


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _is_political(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in POLITICAL_KEYWORDS)


def _is_excluded(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EXCLUDED_KEYWORDS)


def _fetch_news(query: str, n: int = 4) -> list[dict]:
    try:
        return list(DDGS().news(query, max_results=n))
    except Exception:
        return []


def _news_snippet(news: list[dict]) -> str:
    lines = []
    for item in news:
        d = item.get("date", "")[:10]
        t = item.get("title", "?")
        b = (item.get("body") or "")[:120]
        lines.append(f"  [{d}] {t}\n  {b}")
    return "\n".join(lines) if lines else "  (no recent news found)"


class ResolutionHunterV2Strategy(Strategy):
    name = "resolution_hunter_v2"
    edge_type = "resolution_lag"
    time_window = "short"
    target_hold_min_days = 1
    target_hold_max_days = 14
    scan_frequency = "3x/day"
    max_position_usdc = 12.0
    min_ev_pp = 20.0     # higher bar than v1 (was 15)
    alert_only = True
    trading_enabled = False
    promotable = True
    promotion_criteria = "20 alerts with >60% directional accuracy"
    signal_cooldown_hours = 48.0  # near-resolution markets don't change hourly
    last_check_details: list[dict] = []
    fast_dry_run_candidates = 4

    def _candidate_score(self, title: str, days: int, vol: float, news_count: int) -> float:
        score = 0.0
        score += min(vol / 50_000, 2.0)
        score += 2.0 / max(days, 1)
        score += min(news_count, 4) * 0.5
        return score

    def _check_batch(self, candidates: list[dict]) -> list[dict]:
        today = date.today().isoformat()
        market_blocks = []
        for c in candidates:
            market_blocks.append(
                f"slug={c['slug']} | price={c['yes_price']*100:.0f}% YES | closes={c['closes']} | score={c['score']:.2f}\n"
                f"Title: {c['title']}\nRecent news:\n{_news_snippet(c['news'])}"
            )
        prompt = (
            f"Today is {today}. You are checking Polymarket prediction markets about political, "
            f"regulatory, or diplomatic events to find ones where the underlying event has "
            f"ALREADY HAPPENED but the market still shows a non-trivial price.\n"
            f"Only flag markets where you are at least 90% confident the event has already resolved.\n"
            f"Return JSON array. Each object: {{\"slug\": \"...\", \"outcome\": \"YES or NO\", "
            f"\"confidence\": 0-100, \"reason\": \"one sentence\"}}\n"
            f"If no markets have clearly resolved, return an empty array [].\n"
            f"MARKETS:\n{'='*60}\n"
            + "\n".join(f"[{i+1}] {b}" for i, b in enumerate(market_blocks))
            + f"\n{'='*60}"
        )
        response = call_claude(prompt, max_tokens=1024)
        if "[LLM" in response:
            return []
        # Extract JSON from response
        try:
            # Try direct parse first
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                raw = json.loads(match.group(0))
                return [r for r in raw if isinstance(r, dict) and r.get("confidence", 0) >= 90]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        candidates = []

        for ev in markets:
            title = ev.get("title") or "?"
            if _is_excluded(title):
                continue
            if not _is_political(title):
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

            news = _fetch_news(title, n=4)
            if len(news) < 2:
                continue

            score = self._candidate_score(title, days, vol, len(news))
            slug = ev.get("slug", "") or str(ev.get("id", ""))
            candidates.append({
                "slug": slug,
                "title": title,
                "yes_price": yes_price,
                "closes": (ev.get("endDate") or "")[:10],
                "url": event_url(ev),
                "score": score,
                "news": news,
            })
            self.last_check_details.append({
                "market_slug": slug,
                "title": title,
                "candidate_score": score,
                "news_count": len(news),
                "claude_confidence": None,
                "claude_outcome": None,
                "decision": "candidate",
                "reason": "ranked_for_batching",
            })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        candidates = candidates[:getattr(self, "_fast_dry_run_candidates_override", MAX_CANDIDATES)]
        print(f"  [{self.name}] {len(candidates)} political candidates → checking with Claude...")

        if not candidates:
            print(f"  [{self.name}] 0 signals")
            return []

        slug_to_candidate = {c["slug"]: c for c in candidates}
        resolved_hits = []
        for i in range(0, len(candidates), BATCH_SIZE):
            hits = self._check_batch(candidates[i:i + BATCH_SIZE])
            for hit in hits:
                cand = slug_to_candidate.get(hit.get("slug", ""), {})
                self.last_check_details.append({
                    "market_slug": hit.get("slug"),
                    "title": cand.get("title"),
                    "candidate_score": cand.get("score"),
                    "news_count": len(cand.get("news", [])),
                    "claude_confidence": hit.get("confidence"),
                    "claude_outcome": hit.get("outcome"),
                    "decision": "resolved_hit",
                    "reason": hit.get("reason"),
                })
            resolved_hits.extend(hits)

        signals = []
        for hit in resolved_hits:
            slug = hit.get("slug", "")
            c = slug_to_candidate.get(slug)
            if not c:
                continue
            outcome = hit.get("outcome", "").upper()
            if outcome not in ("YES", "NO"):
                continue
            yes_price = c["yes_price"]
            p_hat = min(hit["confidence"] / 100, 0.99)
            mp = yes_price if outcome == "YES" else round(1 - yes_price, 4)
            ev_pp = (p_hat - mp) * 100
            if ev_pp < self.min_ev_pp:
                continue
            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=c["title"][:100],
                outcome=outcome,
                market_price=mp,
                p_hat=round(p_hat, 3),
                ev_pp=round(ev_pp, 1),
                confidence="high" if hit["confidence"] >= 95 else "medium",
                closes=c["closes"],
                url=c["url"],
                rationale=f"resolved-v2:{hit.get('reason', '?')[:80]}",
            ))

        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

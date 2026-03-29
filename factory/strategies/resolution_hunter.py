"""
Strategy: resolution_hunter
Hypothesis: Some markets continue trading at non-trivial prices (10–85%) after the
            underlying event has already happened — because Polymarket settlement lags
            real-world resolution. Buying the correct side captures near-certain EV.
Method: Scan markets closing within 0–45 days, priced 10–85%. Fetch recent news per
        market, ask Claude: "Has this event resolved? What's the correct probability?"
        Only trade when Claude is >90% confident and EV ≥ min_ev_pp.
Cost: ~1 Claude call per candidate (batched). Runs after top-100 fetch.
"""
import json
import re
from datetime import date, datetime

from ddgs import DDGS

from ..claude import call_claude
from ..feed import event_url, fetch_by_tag, format_date, get_yes_price, markets_to_text
from ..models import Signal
from .base import Strategy

MAX_DAYS = 45
MIN_DAYS = 0
MIN_PRICE = 0.10   # skip markets already priced >90% or <10%
MAX_PRICE = 0.85
MIN_VOLUME = 2_000
BATCH_SIZE = 8     # markets per Claude call


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


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


class ResolutionHunterStrategy(Strategy):
    name = "resolution_hunter"
    max_position_usdc = 20.0
    min_ev_pp = 15.0
    min_position_usdc = 2.0

    def _check_batch(self, candidates: list[dict]) -> list[dict]:
        """
        Ask Claude whether any of these markets have already resolved.
        Returns list of {slug, outcome, confidence_pct, reason}.
        """
        today = date.today().isoformat()

        # Fetch news for each candidate
        market_blocks = []
        for c in candidates:
            news = _fetch_news(c["title"], n=4)
            block = (
                f"slug={c['slug']} | price={c['yes_price']*100:.0f}% YES | "
                f"closes={c['closes']}\n"
                f"Title: {c['title']}\n"
                f"Recent news:\n{_news_snippet(news)}"
            )
            market_blocks.append(block)

        prompt = f"""Today is {today}. You are checking Polymarket prediction markets to find ones
where the underlying event has ALREADY HAPPENED but the market still shows a non-trivial price.

For each market below, answer:
1. Has the event definitely already resolved in the real world?
2. If yes — what is the correct answer (YES or NO to the market question)?
3. How confident are you (0–100%)?

Only flag markets where you are ≥85% confident the event has already resolved with a clear outcome.

MARKETS:
{"="*60}
{chr(10).join(f"[{i+1}] {b}" for i, b in enumerate(market_blocks))}
{"="*60}

Return JSON inside <resolved> tags. Include ONLY markets you're confident have resolved.
Each object: {{"slug": "...", "outcome": "YES or NO", "confidence": 0-100, "reason": "one sentence"}}
<resolved>[]</resolved>"""

        response = call_claude(prompt, max_tokens=1024)
        match = re.search(r"<resolved>(.*?)</resolved>", response, re.DOTALL)
        if not match:
            return []
        try:
            raw = json.loads(match.group(1).strip())
            return [r for r in raw if isinstance(r, dict) and r.get("confidence", 0) >= 85]
        except (json.JSONDecodeError, TypeError):
            return []

    def scan(self, markets: list[dict]) -> list[Signal]:
        today = date.today().isoformat()

        # Collect candidates: open, non-extreme price, closes within window
        candidates = []
        for ev in markets:
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
                continue
            yes_price = get_yes_price(ev)
            if yes_price is None or not (MIN_PRICE <= yes_price <= MAX_PRICE):
                continue

            candidates.append({
                "slug": ev.get("slug", "") or str(ev.get("id", "")),
                "title": ev.get("title") or "?",
                "yes_price": yes_price,
                "closes": (ev.get("endDate") or "")[:10],
                "url": event_url(ev),
            })

        print(f"  [{self.name}] {len(candidates)} candidates → checking with Claude...")

        if not candidates:
            print(f"  [{self.name}] 0 signals")
            return []

        # Process in batches
        resolved_hits = []
        for i in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[i: i + BATCH_SIZE]
            hits = self._check_batch(batch)
            resolved_hits.extend(hits)
            if hits:
                print(f"  [{self.name}] batch {i//BATCH_SIZE+1}: {len(hits)} resolved found")

        # Build signals
        slug_to_candidate = {c["slug"]: c for c in candidates}
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
            if outcome == "YES":
                p_hat = min(hit["confidence"] / 100, 0.99)
                mp = yes_price
            else:
                p_hat = min(hit["confidence"] / 100, 0.99)
                mp = round(1 - yes_price, 4)

            ev_pp = (p_hat - mp) * 100
            if ev_pp < self.min_ev_pp:
                continue

            conf_label = "high" if hit["confidence"] >= 95 else "medium"
            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=c["title"][:100],
                outcome=outcome,
                market_price=mp,
                p_hat=round(p_hat, 3),
                ev_pp=round(ev_pp, 1),
                confidence=conf_label,
                closes=c["closes"],
                url=c["url"],
                rationale=f"resolved:{hit.get('reason','?')[:80]}",
            ))

        print(f"  [{self.name}] {len(signals)} signals")
        return signals

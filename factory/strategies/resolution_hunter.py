"""
Strategy: resolution_hunter
Look for markets that appear already resolved in the real world but not yet settled by the market.
"""
import json
import re
from datetime import date

from ddgs import DDGS

from ..claude import call_claude
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MAX_DAYS = 45
MIN_DAYS = 0
MIN_PRICE = 0.15
MAX_PRICE = 0.75
MIN_VOLUME = 5_000
BATCH_SIZE = 6
MAX_CANDIDATES = 18
LIKELY_RESOLVED_KEYWORDS = ["will", "by", "before", "on", "this month", "end of", "ceasefire", "strike", "decision", "visit", "winner", "wins", "resign", "out by", "ban", "approve"]
AMBIGUOUS_KEYWORDS = ["price", "$", "temperature", "spread", "how many", "what percent", "volume of"]
NEWSY_KEYWORDS = ["trump", "fed", "iran", "israel", "gaza", "ceasefire", "election", "tariff", "war", "strike", "ukraine", "bitcoin", "sec", "musk", "netanyahu", "houthi"]


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
    last_check_details: list[dict] = []
    edge_type = "resolution_lag"
    time_window = "short"
    target_hold_min_days = 0.04
    target_hold_max_days = 7
    scan_frequency = "3x/day"
    max_position_usdc = 20.0
    min_ev_pp = 15.0
    min_position_usdc = 2.0
    fast_dry_run_candidates = 6

    def _candidate_score(self, title: str, days: int, vol: float) -> float:
        tl = title.lower()
        if any(k in tl for k in AMBIGUOUS_KEYWORDS):
            return -1.0
        score = 0.0
        if any(k in tl for k in LIKELY_RESOLVED_KEYWORDS):
            score += 3.0
        if any(k in tl for k in NEWSY_KEYWORDS):
            score += 2.0
        if "?" in title:
            score += 0.5
        score += min(vol / 20_000, 3.0)
        score += 2.5 / max(days + 1, 1)
        return score

    def _check_batch(self, candidates: list[dict]) -> list[dict]:
        today = date.today().isoformat()
        market_blocks = []
        for c in candidates:
            market_blocks.append(
                f"slug={c['slug']} | price={c['yes_price']*100:.0f}% YES | closes={c['closes']} | score={c['score']:.2f}\n"
                f"Title: {c['title']}\nRecent news:\n{_news_snippet(c['news'])}"
            )
        prompt = f"""Today is {today}. You are checking Polymarket prediction markets to find ones where the underlying event has ALREADY HAPPENED but the market still shows a non-trivial price.
Only flag markets where you are at least 85% confident the event has already resolved.
Return JSON inside <resolved> tags. Include ONLY markets you're confident have resolved.
Each object: {{"slug": "...", "outcome": "YES or NO", "confidence": 0-100, "reason": "one sentence"}}
MARKETS:\n{"="*60}\n{chr(10).join(f'[{i+1}] {b}' for i, b in enumerate(market_blocks))}\n{"="*60}\n<resolved>[]</resolved>"""
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
        self.last_check_details = []
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
            title = ev.get("title") or "?"
            score = self._candidate_score(title, days, vol)
            if score < 0:
                continue
            news = _fetch_news(title, n=4)
            if len(news) < 2 and not any(k in title.lower() for k in NEWSY_KEYWORDS):
                continue
            candidate_score = score + min(len(news), 4) * 0.4
            slug = ev.get("slug", "") or str(ev.get("id", ""))
            candidates.append({"slug": slug, "title": title, "yes_price": yes_price, "closes": (ev.get("endDate") or "")[:10], "url": event_url(ev), "score": candidate_score, "news": news})
            self.last_check_details.append({"market_slug": slug, "title": title, "candidate_score": candidate_score, "news_count": len(news), "claude_confidence": None, "claude_outcome": None, "decision": "candidate", "reason": "ranked_for_batching"})

        candidates.sort(key=lambda c: c["score"], reverse=True)
        candidates = candidates[:getattr(self, "_fast_dry_run_candidates_override", MAX_CANDIDATES)]
        print(f"  [{self.name}] {len(candidates)} ranked candidates → checking with Claude...")
        if not candidates:
            print(f"  [{self.name}] 0 signals")
            return []

        slug_to_candidate = {c["slug"]: c for c in candidates}
        resolved_hits = []
        for i in range(0, len(candidates), BATCH_SIZE):
            hits = self._check_batch(candidates[i:i + BATCH_SIZE])
            for hit in hits:
                cand = slug_to_candidate.get(hit.get("slug", ""), {})
                self.last_check_details.append({"market_slug": hit.get("slug"), "title": cand.get("title"), "candidate_score": cand.get("score"), "news_count": len(cand.get("news", [])), "claude_confidence": hit.get("confidence"), "claude_outcome": hit.get("outcome"), "decision": "resolved_hit", "reason": hit.get("reason")})
            resolved_hits.extend(hits)
            if hits:
                print(f"  [{self.name}] batch {i//BATCH_SIZE+1}: {len(hits)} resolved found")

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
            conf_label = "high" if hit["confidence"] >= 95 else "medium"
            signals.append(Signal(strategy=self.name, market_id=slug, market_title=c["title"][:100], outcome=outcome, market_price=mp, p_hat=round(p_hat, 3), ev_pp=round(ev_pp, 1), confidence=conf_label, closes=c["closes"], url=c["url"], rationale=f"resolved-v2:{hit.get('reason','?')[:80]}"))

        print(f"  [{self.name}] {len(signals)} signals")
        return signals

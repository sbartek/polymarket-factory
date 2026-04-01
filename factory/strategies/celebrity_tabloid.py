"""
Strategy: celebrity_tabloid
Hypothesis: Celebrity markets can temporarily lag when gossip/tabloid outlets point
to a concrete personal-event outcome before Polymarket fully reprices.
Method: Deterministic celebrity-market screener + fail-closed gossip corroboration.
This MVP is intentionally alert-only and should produce few alerts.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

from ddgs import DDGS

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

GOSSIP_DOMAINS = (
    "people.com",
    "tmz.com",
    "pagesix.com",
    "usmagazine.com",
    "eonline.com",
    "okmagazine.com",
    "dailymail.co.uk",
)
ENTERTAINMENT_TERMS = {
    "celebrity", "celebrities", "entertainment", "gossip", "tabloid", "hollywood",
    "music", "movies", "tv", "television", "film", "actor", "actress", "singer",
    "rapper", "influencer", "model", "reality tv", "reality",
}
EXCLUDED_TERMS = {
    "election", "president", "senate", "governor", "prime minister", "congress",
    "bitcoin", "crypto", "ethereum", "stocks", "fed", "inflation", "tariff",
    "soccer", "football", "nba", "nfl", "mlb", "nhl", "ufc", "tennis",
}
NAME_STOPWORDS = {
    "Will", "Did", "Can", "Could", "Who", "What", "When", "Where", "Why", "How",
    "The", "A", "An", "In", "On", "At", "By", "And", "Or", "Of", "For", "To",
    "With", "From", "Before", "After", "Get", "Gets", "Is", "Are", "Be", "Have",
    "Has", "Into", "Over", "Under", "By", "End", "Season", "Year", "Award",
}
SUPPORT_PHRASES = {
    "romance_up": {"dating", "engaged", "engagement", "married", "marriage", "wedding", "together", "reconcile", "rekindle", "romance", "ring"},
    "romance_down": {"breakup", "break", "split", "divorce", "divorced", "separate", "separated", "cheating", "affair"},
    "pregnancy": {"pregnant", "pregnancy", "expecting", "baby", "baby bump"},
    "scandal": {"arrested", "arrest", "lawsuit", "sued", "rehab", "hospitalized", "hospital", "charged"},
}
CONTRADICTION_PHRASES = {
    "romance_up": {"split", "breakup", "divorce", "not dating", "denies"},
    "romance_down": {"back together", "together", "engaged", "married", "denies"},
    "pregnancy": {"not pregnant", "denies", "shuts down rumors", "false rumor"},
    "scandal": {"dismissed", "cleared", "denies", "debunked"},
}
EVENT_FAMILY_PATTERNS = [
    ("pregnancy", re.compile(r"\b(pregnan|expecting|baby)\w*\b", re.IGNORECASE)),
    ("romance_up", re.compile(r"\b(dating|engag|marri|wedding|reconcil|rekindl|together)\w*\b", re.IGNORECASE)),
    ("romance_down", re.compile(r"\b(breakup|break up|split|divorc|cheat|affair|separat)\w*\b", re.IGNORECASE)),
    ("scandal", re.compile(r"\b(arrest|lawsuit|sue|rehab|hospitaliz|charged)\w*\b", re.IGNORECASE)),
]
MIN_VOLUME = 10_000
MIN_PRICE = 0.12
MAX_PRICE = 0.88
MIN_DAYS = 1
MAX_DAYS = 45
MIN_CANDIDATE_SCORE = 4.0
MIN_CORROBORATING_HITS = 2
MIN_CORROBORATION_SCORE = 2.5
MAX_ALERTS_PER_RUN = 3


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _collect_text(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            if key in {"name", "slug", "label", "title", "category", "ticker", "series"}:
                out.extend(_collect_text(item))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_collect_text(item))
        return out
    return []


def _market_text(ev: dict) -> str:
    return " | ".join(_collect_text({
        "title": ev.get("title"),
        "category": ev.get("category"),
        "tags": ev.get("tags"),
        "series": ev.get("series"),
    }))


def _extract_names(title: str, ev: dict) -> list[str]:
    names: list[str] = []
    patterns = re.findall(r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", title or "")
    for raw in patterns:
        tokens = [token for token in raw.split() if token not in NAME_STOPWORDS]
        if not tokens:
            continue
        if len(tokens) == 1 and len(tokens[0]) < 5:
            continue
        cleaned = " ".join(tokens[:3]).strip()
        if cleaned and cleaned not in names:
            names.append(cleaned)

    for tag in ev.get("tags") or []:
        label = str(tag.get("label") or tag.get("slug") or "").strip()
        if re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", label) and label not in names:
            names.append(label)
    return names[:3]


def _event_family(title: str) -> str | None:
    for family, pattern in EVENT_FAMILY_PATTERNS:
        if pattern.search(title or ""):
            return family
    return None


def _candidate_score(volume: float, price: float, days: int, entertainment_match: bool, name_count: int) -> float:
    score = 0.0
    score += 2.0 if entertainment_match else 0.0
    score += 1.0 if name_count >= 1 else 0.0
    score += 1.0 if name_count >= 2 else 0.0
    score += 1.0 if volume >= 25_000 else 0.0
    score += 0.5 if volume >= 50_000 else 0.0
    score += 0.5 if 0.2 <= price <= 0.8 else 0.0
    score += 0.5 if days <= 21 else 0.0
    return score


class CelebrityTabloidStrategy(Strategy):
    name = "celebrity_tabloid"
    alert_only = True
    trading_enabled = False
    promotable = True
    live_ready = False
    promotion_criteria = "docs/alert_only_graduation.md#promotion-criteria"
    edge_type = "information"
    time_window = "short"
    target_hold_min_days = 1
    target_hold_max_days = 10
    scan_frequency = "3x/day"
    paused = False
    min_ev_pp = 8.0
    fast_dry_run_candidates = 4
    last_check_details: list[dict] = []

    def _eligible(self, ev: dict) -> dict | None:
        title = str(ev.get("title") or "")
        text = _market_text(ev)
        if any(term in text for term in EXCLUDED_TERMS):
            return None

        family = _event_family(title)
        if not family:
            return None

        price = get_yes_price(ev)
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            return None

        volume = float(ev.get("volume24hr") or ev.get("volume") or 0)
        if volume < MIN_VOLUME:
            return None

        days = _days_to_close(ev.get("endDate"))
        if days is None or days < MIN_DAYS or days > MAX_DAYS:
            return None

        names = _extract_names(title, ev)
        entertainment_match = any(term in text for term in ENTERTAINMENT_TERMS)
        if not entertainment_match and not names:
            return None

        score = _candidate_score(volume, price, days, entertainment_match, len(names))
        if score < MIN_CANDIDATE_SCORE:
            return None

        return {
            "slug": str(ev.get("slug", "") or ev.get("id", "")),
            "title": title or "?",
            "price": price,
            "volume": volume,
            "days_to_close": days,
            "event_family": family,
            "names": names,
            "candidate_score": round(score, 2),
            "url": event_url(ev),
            "closes": (ev.get("endDate") or "")[:10],
        }

    def _fetch_gossip_hits(self, candidate: dict, n: int = 6) -> list[dict]:
        if not candidate["names"]:
            return []
        domain_query = " OR ".join(f"site:{domain}" for domain in GOSSIP_DOMAINS)
        query = f"{' OR '.join(candidate['names'])} {candidate['event_family'].replace('_', ' ')} {domain_query}"
        try:
            return list(DDGS().text(query, max_results=n))
        except Exception:
            return []

    def _score_hits(self, candidate: dict, hits: list[dict]) -> tuple[int, float, float]:
        usable = 0
        support = 0.0
        contradiction = 0.0
        support_terms = SUPPORT_PHRASES[candidate["event_family"]]
        contradiction_terms = CONTRADICTION_PHRASES[candidate["event_family"]]

        for hit in hits:
            href = str(hit.get("href") or "")
            netloc = urlparse(href).netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            if netloc and netloc not in GOSSIP_DOMAINS:
                continue

            text = f"{hit.get('title', '')} {hit.get('body', '')}".lower()
            if candidate["names"] and not any(name.lower() in text for name in candidate["names"]):
                continue

            usable += 1
            if any(term in text for term in support_terms):
                support += 1.5
            if any(term in text for term in contradiction_terms):
                contradiction += 1.0

        return usable, round(support, 2), round(contradiction, 2)

    def _signal_from_candidate(self, candidate: dict, support: float) -> tuple[str, float, str, str]:
        price = candidate["price"]
        pull = min(0.03 + support * 0.03, 0.16)
        outcome = "YES"
        market_price = price
        p_hat = min(price + pull, 0.95)
        confidence = "high" if support >= 4 else "medium"
        rationale = (
            f"tabloid_{candidate['event_family']}: names={','.join(candidate['names']) or 'unknown'}: "
            f"candidate={candidate['candidate_score']:.1f}: support={support:.1f}"
        )
        return outcome, market_price, p_hat, confidence, rationale[:180]

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        candidates = []
        for ev in markets:
            row = self._eligible(ev)
            if row:
                candidates.append(row)

        candidates.sort(
            key=lambda row: (-row["candidate_score"], -row["volume"], row["days_to_close"], row["price"])
        )
        limit = getattr(self, "_fast_dry_run_candidates_override", None)
        if limit is not None:
            candidates = candidates[:limit]

        print(f"  [{self.name}] {len(candidates)} celebrity candidates...")
        signals: list[Signal] = []
        for candidate in candidates:
            hits = self._fetch_gossip_hits(candidate)
            usable_hits, support, contradiction = self._score_hits(candidate, hits)
            net_score = round(support - contradiction, 2)
            decision = "watch"
            reason = "insufficient_gossip_corroboration"

            if usable_hits >= MIN_CORROBORATING_HITS and net_score >= MIN_CORROBORATION_SCORE:
                outcome, market_price, p_hat, confidence, rationale = self._signal_from_candidate(candidate, support)
                ev_pp = round((p_hat - market_price) * 100, 1)
                if ev_pp >= self.min_ev_pp and len(signals) < MAX_ALERTS_PER_RUN:
                    decision = "alert"
                    reason = candidate["event_family"]
                    signals.append(Signal(
                        strategy=self.name,
                        market_id=candidate["slug"],
                        market_title=candidate["title"][:100],
                        outcome=outcome,
                        market_price=round(market_price, 4),
                        p_hat=round(p_hat, 4),
                        ev_pp=ev_pp,
                        confidence=confidence,
                        closes=candidate["closes"],
                        url=candidate["url"],
                        rationale=rationale,
                    ))
                else:
                    reason = "edge_below_threshold"
            elif contradiction > support:
                reason = "contradictory_gossip_coverage"

            self.last_check_details.append({
                "market_slug": candidate["slug"],
                "title": candidate["title"][:120],
                "subject_names": ",".join(candidate["names"]),
                "signal_family": candidate["event_family"],
                "candidate_score": candidate["candidate_score"],
                "news_hits": usable_hits,
                "corroboration_score": net_score,
                "decision": decision,
                "reason": reason,
            })

        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

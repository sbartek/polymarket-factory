"""
Strategy: correlated_pairs
Hypothesis: Some Polymarket markets violate basic logical consistency across linked
            event pairs (e.g. prerequisite vs downstream event, broader vs narrower event).
Method: Heuristic pair discovery first, then a small Claude pass to classify the
        relationship and identify the cheaper implication.

MVP scope deliberately narrow:
- prerequisite pairs (e.g. nomination/primary before election win)
- broader vs narrower event pairs
- single-leg execution only
"""
import json
import re
from datetime import date

from ..claude import call_claude
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_VOLUME = 10_000
MIN_PRICE = 0.08
MAX_PRICE = 0.85
MAX_DAYS = 120
MAX_PAIR_CANDIDATES = 8
MAX_TRADES_PER_RUN = 2
MIN_EV_PP = 10.0
RELATIONSHIP_GAP_PP = 10.0
PAIR_KEYWORDS = [
    "trump", "newsom", "vance", "rubio", "fed", "iran", "china", "tariff",
    "trade war", "war", "ceasefire", "election", "primary", "nominee", "president",
    "nba", "nhl", "mlb", "nfl", "mls",
    "hormuz", "bitcoin", "crypto", "hungary", "ukraine", "russia", "musk",
    "hamas", "israel", "netanyahu", "gaza", "hezbollah",
]


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _topic_keys(title: str) -> set[str]:
    """Return all PAIR_KEYWORDS that appear in the title."""
    tl = title.lower()
    keys = {k for k in PAIR_KEYWORDS if k in tl}
    if not keys:
        words = re.findall(r"[a-zA-Z]{5,}", tl)
        keys = {words[0]} if words else {tl[:24]}
    return keys


class CorrelatedPairsStrategy(Strategy):
    name = "correlated_pairs"
    last_check_details: list[dict] = []
    edge_type = "logical_inconsistency"
    time_window = "medium"
    target_hold_min_days = 3
    target_hold_max_days = 30
    scan_frequency = "daily"
    max_position_usdc = 10.0
    min_ev_pp = MIN_EV_PP
    min_position_usdc = 2.0
    fast_dry_run_candidates = 4
    alert_only = True
    trading_enabled = False  # killed 2026-05-17: 0W/11L, LLM miscalibrates rare-event probabilities

    def _eligible(self, ev: dict) -> bool:
        vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
        if vol < MIN_VOLUME:
            return False
        days = _days_to_close(ev.get("endDate"))
        if days is None or days < 0 or days > MAX_DAYS:
            return False
        price = get_yes_price(ev)
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            return False
        return True

    def _discover_pairs(self, markets: list[dict]) -> list[tuple[dict, dict]]:
        eligible = [m for m in markets if self._eligible(m)]
        by_topic: dict[str, list[dict]] = {}
        for ev in eligible:
            for key in _topic_keys(ev.get("title") or ""):
                by_topic.setdefault(key, []).append(ev)

        seen_pairs: set[tuple[str, str]] = set()
        pairs: list[tuple[dict, dict]] = []
        for topic, group in sorted(by_topic.items(), key=lambda x: -len(x[1])):
            if len(group) < 2:
                continue
            group = sorted(group, key=lambda e: float(e.get("volume24hr") or e.get("volume") or 0), reverse=True)
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a = group[i]
                    b = group[j]
                    if a.get("slug") == b.get("slug"):
                        continue
                    pair_key = tuple(sorted([a.get("slug", ""), b.get("slug", "")]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    pairs.append((a, b))
                    if len(pairs) >= MAX_PAIR_CANDIDATES:
                        return pairs
        return pairs

    def _classify_pairs(self, pairs: list[tuple[dict, dict]]) -> list[dict]:
        if not pairs:
            return []

        pair_text = []
        for i, (a, b) in enumerate(pairs, start=1):
            ap = round((get_yes_price(a) or 0) * 100)
            bp = round((get_yes_price(b) or 0) * 100)
            pair_text.append(
                f"[{i}]\n"
                f"A slug={a.get('slug','')} | {ap}% YES | {a.get('title','?')}\n"
                f"B slug={b.get('slug','')} | {bp}% YES | {b.get('title','?')}"
            )

        prompt = f"""You are checking Polymarket market pairs for logical inconsistency.

Allowed relationships:
- prerequisite: B requires A, so P(B) should not exceed P(A) by much
- broader_event: A is broader than B, so P(narrower) should not exceed P(broader) by much
- narrower_event: inverse of broader_event
- unrelated

For each pair below:
1. classify the relationship
2. identify which slug appears underpriced or overpriced, if any
3. estimate ev_pp only when the inconsistency is clear and material

Return JSON inside <pairs> tags. Include ONLY pairs with a clear relationship and |ev_pp| >= {RELATIONSHIP_GAP_PP}.
Each object:
{{
  "slug": "<underpriced market slug>",
  "title": "<underpriced market title>",
  "outcome": "YES or NO",
  "market_price": <integer 0-100>,
  "p_hat": <integer 0-100>,
  "ev_pp": <signed integer>,
  "confidence": "medium|high",
  "relationship": "prerequisite|broader_event|narrower_event",
  "reason": "one short sentence"
}}

PAIRS:
{"="*60}
{chr(10).join(pair_text)}
{"="*60}

<pairs>[]</pairs>"""

        response = call_claude(prompt, max_tokens=1200)
        match = re.search(r"<pairs>(.*?)</pairs>", response, re.DOTALL)
        if not match:
            return []
        try:
            raw = json.loads(match.group(1).strip())
            return [r for r in raw if isinstance(r, dict)]
        except (json.JSONDecodeError, TypeError):
            return []

    def scan(self, markets: list[dict]) -> list[Signal]:
        pairs = self._discover_pairs(markets)
        limit_pairs = getattr(self, "_fast_dry_run_candidates_override", MAX_PAIR_CANDIDATES)
        pairs = pairs[:limit_pairs]
        for a, b in pairs:
            self.last_check_details.append({
                "slug_a": a.get("slug", "") or str(a.get("id", "")),
                "slug_b": b.get("slug", "") or str(b.get("id", "")),
                "relationship": None,
                "violation_pp": None,
                "chosen_slug": None,
                "decision": "candidate_pair",
                "reason": "topic_group_pairing",
            })
        print(f"  [{self.name}] {len(pairs)} pair candidates → checking logical consistency...")
        if not pairs:
            print(f"  [{self.name}] 0 signals")
            return []

        raw_signals = self._classify_pairs(pairs)
        for item in raw_signals:
            self.last_check_details.append({
                "slug_a": None,
                "slug_b": None,
                "relationship": item.get("relationship"),
                "violation_pp": item.get("ev_pp"),
                "chosen_slug": item.get("slug"),
                "decision": "llm_hit",
                "reason": item.get("reason"),
            })
        slug_to_market = {str(ev.get("slug", "") or ev.get("id", "")): ev for ev in markets}
        signals: list[Signal] = []
        seen = set()

        for item in raw_signals:
            slug = item.get("slug", "")
            ev = slug_to_market.get(slug)
            if not ev or slug in seen:
                continue
            confidence = (item.get("confidence", "medium") or "medium").lower()
            if confidence not in ("medium", "high"):
                continue
            ev_pp = float(item.get("ev_pp", 0))
            if abs(ev_pp) < self.min_ev_pp:
                continue

            outcome = (item.get("outcome", "YES") or "YES").upper()
            mp_pct = float(item.get("market_price", round((get_yes_price(ev) or 0.5) * 100)))
            ph_pct = float(item.get("p_hat", 50))
            mp = (100 - mp_pct) / 100 if outcome == "NO" else mp_pct / 100
            ph = (100 - ph_pct) / 100 if outcome == "NO" else ph_pct / 100

            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=(item.get("title") or ev.get("title") or "?")[:100],
                outcome=outcome,
                market_price=round(mp, 4),
                p_hat=round(ph, 4),
                ev_pp=round(abs(ev_pp), 1),
                confidence=confidence,
                closes=(ev.get("endDate") or "")[:10],
                url=event_url(ev),
                rationale=f"corr:{item.get('relationship','?')}:{item.get('reason','?')[:80]}",
            ))
            seen.add(slug)
            if len(signals) >= MAX_TRADES_PER_RUN:
                break

        print(f"  [{self.name}] {len(signals)} signals")
        return signals

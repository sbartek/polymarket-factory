"""
Strategy: conditional_probability_mispricing
Hypothesis: When market A logically implies market B, P(B) >= P(A) must
            hold. Violations are pure logical arbitrage.

Three violation patterns:
1. Nested thresholds (same event): "above $220" implies "above $215",
   so P($215) >= P($220). If violated, buy the underpriced lower threshold.
2. Nested deadlines (related events): "X by April" implies "X by June",
   so P(June) >= P(April). If violated, buy the underpriced later deadline.
3. Stage chains: "wins semifinal" implies "wins final" is possible,
   so P(final) <= P(semifinal). If violated, sell the overpriced downstream.

Method: Deterministic — parse thresholds/dates/stages from titles,
check for ordering violations, signal when gap > fee threshold.
No LLM, no external API.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_VOLUME = 5_000
MIN_GAP_PP = 3.0
MAX_ALERTS_PER_RUN = 5

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Stage chains: earlier stage is prerequisite for later stage
STAGE_CHAINS = [
    ["qualify", "group stage", "round of 16", "quarterfinal", "semifinal", "final", "winner", "champion"],
    ["make playoffs", "win first round", "win second round", "conference finals", "win championship"],
    ["wild card", "divisional", "championship", "super bowl"],
    ["play-in", "first round", "second round", "conference", "finals", "champion"],
    ["primary", "nomination", "nominee", "general election", "win election", "president"],
]

_STAGE_LOOKUP: dict[str, list[tuple[int, int]]] = {}
for _ci, _chain in enumerate(STAGE_CHAINS):
    for _si, _stage in enumerate(_chain):
        _STAGE_LOOKUP.setdefault(_stage, []).append((_ci, _si))

TOPIC_KEYWORDS = [
    "trump", "vance", "rubio", "desantis", "harris", "biden",
    "fed", "iran", "china", "tariff", "ukraine", "russia",
    "nba", "nhl", "mlb", "nfl", "uefa", "champions league",
    "lakers", "celtics", "warriors", "real madrid", "barcelona", "arsenal",
    "bitcoin", "ethereum",
]


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _get_market_price(market: dict) -> float | None:
    raw = market.get("outcomePrices", "[]")
    try:
        prices = json.loads(raw) if isinstance(raw, str) else raw
        return float(prices[0]) if prices else None
    except (ValueError, TypeError, IndexError):
        return None


def _parse_threshold(title: str) -> float | None:
    """Extract numeric threshold from 'above $X' or 'X or higher' patterns."""
    for pattern in [
        r"above \$?([\d,]+(?:\.\d+)?)\s*([BMK])?",
        r"at least \$?([\d,]+(?:\.\d+)?)\s*([BMK])?",
        r"(\d+(?:\.\d+)?)°[FCfc]\s+or (?:higher|above)",
    ]:
        m = re.search(pattern, title, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "")
            val = float(raw)
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                s = m.group(2).upper()
                if s == "B": val *= 1e9
                elif s == "M": val *= 1e6
                elif s == "K": val *= 1e3
            return val
    return None


def _parse_deadline_rank(title: str) -> int | None:
    """Sortable rank from 'by <date>'. Higher = later deadline."""
    m = re.search(
        r"by\s+(?:end of\s+)?(january|february|march|april|may|june|july|"
        r"august|september|october|november|december)\s*(\d{1,2})?",
        title, re.IGNORECASE,
    )
    if m:
        month = MONTH_MAP.get(m.group(1).lower(), 0)
        day = int(m.group(2)) if m.group(2) else 28
        return month * 100 + day
    m = re.search(r"by\s+end of\s+(\d{4})", title, re.IGNORECASE)
    if m:
        return 13 * 100
    return None


def _extract_stages(title: str) -> list[tuple[int, int]]:
    tl = title.lower()
    matches = []
    for keyword, positions in _STAGE_LOOKUP.items():
        if keyword in tl:
            matches.extend(positions)
    return matches


def _topic_keys(title: str) -> set[str]:
    tl = title.lower()
    keys = {k for k in TOPIC_KEYWORDS if k in tl}
    if not keys:
        words = re.findall(r"[a-zA-Z]{5,}", tl)
        keys = {words[0]} if words else set()
    return keys


class ConditionalProbabilityMispricingStrategy(Strategy):
    name = "conditional_probability_mispricing"
    edge_type = "logical_inconsistency"
    time_window = "short"
    target_hold_min_days = 0.5
    target_hold_max_days = 14.0
    scan_frequency = "3x/day"
    max_position_usdc = 10.0
    min_ev_pp = MIN_GAP_PP
    alert_only = True
    trading_enabled = False
    promotable = True
    promotion_criteria = "20 signals with >70% profit (violations should revert reliably)"
    signal_cooldown_hours = 12.0
    last_check_details: list[dict] = []

    def _find_threshold_violations(self, ev: dict) -> list[dict]:
        """Nested threshold violations within a single event."""
        markets_list = ev.get("markets") or []
        parsed = []
        for m in markets_list:
            if m.get("closed"):
                continue
            q = m.get("question") or ""
            threshold = _parse_threshold(q)
            if threshold is None:
                continue
            price = _get_market_price(m)
            if price is None or price < 0.02 or price > 0.98:
                continue
            parsed.append({
                "question": q, "market_id": str(m.get("id", "")),
                "threshold": threshold, "price": price,
            })

        if len(parsed) < 2:
            return []

        parsed.sort(key=lambda x: x["threshold"])
        violations = []
        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                lo = parsed[i]  # lower threshold → should have HIGHER price
                hi = parsed[j]
                if hi["price"] > lo["price"] + MIN_GAP_PP / 100:
                    gap = round((hi["price"] - lo["price"]) * 100, 1)
                    violations.append({
                        "type": "threshold",
                        "buy_id": f"{ev.get('slug', '')}:{lo['market_id']}",
                        "buy_title": lo["question"],
                        "buy_price": lo["price"],
                        "sell_id": f"{ev.get('slug', '')}:{hi['market_id']}",
                        "sell_title": hi["question"],
                        "sell_price": hi["price"],
                        "gap_pp": gap,
                        "closes": (ev.get("endDate") or "")[:10],
                        "url": event_url(ev),
                        "rationale": f"threshold:${lo['threshold']:,.0f}@{lo['price']:.0%}<${hi['threshold']:,.0f}@{hi['price']:.0%}",
                    })
        return violations

    def _find_deadline_violations(self, markets: list[dict]) -> list[dict]:
        """Nested deadline violations across related events."""
        families: dict[str, list[dict]] = defaultdict(list)
        for ev in markets:
            title = ev.get("title", "")
            price = get_yes_price(ev)
            if price is None or price < 0.02 or price > 0.98:
                continue
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            m = re.match(r"(.{15,}?)\s+by\b", title, re.IGNORECASE)
            if not m:
                continue
            base = re.sub(r"\s+", " ", m.group(1).strip().lower())
            rank = _parse_deadline_rank(title)
            if rank is None:
                continue
            families[base].append({
                "title": title, "slug": ev.get("slug", ""), "price": price,
                "rank": rank, "url": event_url(ev),
                "closes": (ev.get("endDate") or "")[:10],
            })

        violations = []
        for base, members in families.items():
            if len(members) < 2:
                continue
            members.sort(key=lambda x: x["rank"])
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    earlier = members[i]
                    later = members[j]
                    # Earlier deadline should have LOWER price
                    if earlier["price"] > later["price"] + MIN_GAP_PP / 100:
                        gap = round((earlier["price"] - later["price"]) * 100, 1)
                        violations.append({
                            "type": "deadline",
                            "buy_id": later["slug"],
                            "buy_title": later["title"],
                            "buy_price": later["price"],
                            "sell_id": earlier["slug"],
                            "sell_title": earlier["title"],
                            "sell_price": earlier["price"],
                            "gap_pp": gap,
                            "closes": later["closes"],
                            "url": later["url"],
                            "rationale": f"deadline:{earlier['title'][:30]}@{earlier['price']:.0%}>{later['title'][:30]}@{later['price']:.0%}",
                        })
        return violations

    def _find_stage_violations(self, markets: list[dict]) -> list[dict]:
        """Stage chain violations across related events."""
        eligible = []
        for ev in markets:
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or days < 0 or days > 30:
                continue
            price = get_yes_price(ev)
            if price is None or price < 0.08 or price > 0.92:
                continue
            title = ev.get("title") or ""
            stages = _extract_stages(title)
            if not stages:
                continue
            eligible.append({
                "title": title, "slug": ev.get("slug", ""), "price": price,
                "stages": stages, "url": event_url(ev),
                "closes": (ev.get("endDate") or "")[:10],
            })

        by_topic: dict[str, list[dict]] = defaultdict(list)
        for info in eligible:
            for key in _topic_keys(info["title"]):
                by_topic[key].append(info)

        violations = []
        seen_pairs: set[tuple[str, str]] = set()
        for topic, group in by_topic.items():
            if len(group) < 2:
                continue
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    pair = tuple(sorted([a["slug"], b["slug"]]))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    for ca, sa in a["stages"]:
                        for cb, sb in b["stages"]:
                            if ca != cb or sa == sb:
                                continue
                            if sa < sb:
                                prereq, downstream = a, b
                            else:
                                prereq, downstream = b, a
                            if downstream["price"] > prereq["price"] + MIN_GAP_PP / 100:
                                gap = round((downstream["price"] - prereq["price"]) * 100, 1)
                                violations.append({
                                    "type": "stage",
                                    "buy_id": prereq["slug"],
                                    "buy_title": prereq["title"],
                                    "buy_price": prereq["price"],
                                    "sell_id": downstream["slug"],
                                    "sell_title": downstream["title"],
                                    "sell_price": downstream["price"],
                                    "gap_pp": gap,
                                    "closes": downstream["closes"],
                                    "url": downstream["url"],
                                    "rationale": f"stage:{prereq['title'][:25]}@{prereq['price']:.0%}<{downstream['title'][:25]}@{downstream['price']:.0%}",
                                })
        return violations

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        all_violations: list[dict] = []

        # Pattern 1: Threshold violations within same event
        for ev in markets:
            if len(ev.get("markets") or []) < 2:
                continue
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            all_violations.extend(self._find_threshold_violations(ev))

        # Pattern 2: Deadline violations across related events
        all_violations.extend(self._find_deadline_violations(markets))

        # Pattern 3: Stage chain violations
        all_violations.extend(self._find_stage_violations(markets))

        all_violations.sort(key=lambda v: v["gap_pp"], reverse=True)

        signals: list[Signal] = []
        seen: set[str] = set()

        n_threshold = sum(1 for v in all_violations if v["type"] == "threshold")
        n_deadline = sum(1 for v in all_violations if v["type"] == "deadline")
        n_stage = sum(1 for v in all_violations if v["type"] == "stage")

        for v in all_violations:
            buy_id = v["buy_id"]
            if buy_id in seen:
                continue
            seen.add(buy_id)

            self.last_check_details.append({
                "market_slug": buy_id,
                "title": v["buy_title"][:80],
                "violation_type": v["type"],
                "gap_pp": v["gap_pp"],
                "buy_price": round(v["buy_price"], 4),
                "sell_price": round(v["sell_price"], 4),
                "decision": "alert",
                "reason": v["rationale"][:80],
            })

            # Signal: buy the underpriced side
            signals.append(Signal(
                strategy=self.name,
                market_id=buy_id,
                market_title=v["buy_title"][:100],
                outcome="YES",
                market_price=round(v["buy_price"], 4),
                p_hat=round(min(v["sell_price"] + 0.01, 0.99), 4),
                ev_pp=v["gap_pp"],
                confidence="high" if v["gap_pp"] >= 5 else "medium",
                closes=v.get("closes", ""),
                url=v.get("url", ""),
                rationale=v["rationale"][:180],
            ))

            if len(signals) >= MAX_ALERTS_PER_RUN:
                break

        print(f"  [{self.name}] {len(all_violations)} violations "
              f"({n_threshold} threshold, {n_deadline} deadline, {n_stage} stage), "
              f"{len(signals)} alerts")
        return signals

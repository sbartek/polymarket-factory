"""
Strategy: conditional_probability_mispricing
Hypothesis: When market A is a necessary condition for market B,
P(B) can never exceed P(A). If it does, B is overpriced → bet NO on B.

Pure structural/logical edge — no LLM needed.
Restricted to short-term markets (closing within 14 days) for fast learning.

Examples:
- "Team X wins semifinal" (A) is required for "Team X wins final" (B)
- "Candidate wins primary" (A) is required for "Candidate wins general" (B)
- If P(final) > P(semifinal), the final is overpriced.
"""
import json
import re
from dataclasses import dataclass
from datetime import date

from ..feed import event_url
from ..models import Signal
from .base import Strategy

MIN_VOLUME = 5_000
MIN_PRICE = 0.08
MAX_PRICE = 0.85
MAX_DAYS_TO_CLOSE = 14
MIN_DAYS_TO_CLOSE = 0
MAX_SIGNALS_PER_RUN = 3
MIN_VIOLATION_PP = 5.0  # minimum mispricing to trigger

# Ordered stages: earlier stage is prerequisite for later stage
STAGE_CHAINS = [
    # Sports tournaments
    ["qualify", "group stage", "round of 16", "quarterfinal", "semifinal", "final", "winner", "champion"],
    ["make playoffs", "win first round", "win second round", "conference finals", "win championship"],
    ["wild card", "divisional", "championship", "super bowl"],
    ["play-in", "first round", "second round", "conference", "finals", "champion"],
    # Political
    ["primary", "nomination", "nominee", "general election", "win election", "president"],
    ["qualify", "advance", "win"],
]

# Flatten to a lookup: keyword → (chain_index, stage_index)
_STAGE_LOOKUP: dict[str, list[tuple[int, int]]] = {}
for _ci, _chain in enumerate(STAGE_CHAINS):
    for _si, _stage in enumerate(_chain):
        _STAGE_LOOKUP.setdefault(_stage, []).append((_ci, _si))

# Keywords for grouping related markets by topic
TOPIC_KEYWORDS = [
    "trump", "newsom", "vance", "rubio", "desantis", "harris", "biden",
    "fed", "iran", "china", "tariff", "ukraine", "russia",
    "nba", "nhl", "mlb", "nfl", "mls", "uefa", "champions league",
    "world cup", "copa", "euro", "olympics",
    "lakers", "celtics", "warriors", "knicks", "nuggets", "thunder",
    "yankees", "dodgers", "mets", "braves",
    "chiefs", "eagles", "bills", "lions", "ravens",
    "real madrid", "barcelona", "manchester", "arsenal", "liverpool",
    "bitcoin", "ethereum", "crypto",
]


@dataclass
class MarketInfo:
    slug: str
    title: str
    yes_price: float
    volume: float
    days_to_close: int
    closes: str
    url: str
    event: dict
    stages: list[tuple[int, int]]  # (chain_index, stage_index) matches


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _extract_stages(title: str) -> list[tuple[int, int]]:
    """Find which stage chain positions this title matches."""
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


def _get_yes_price(ev: dict) -> float | None:
    for m in ev.get("markets", []):
        if m.get("closed"):
            continue
        prices_raw = m.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if prices:
                return float(prices[0])
        except (ValueError, TypeError, IndexError):
            continue
    return None


class ConditionalProbabilityMispricingStrategy(Strategy):
    name = "conditional_probability_mispricing"
    last_check_details: list[dict] = []
    edge_type = "logical_inconsistency"
    time_window = "short"
    target_hold_min_days = 0
    target_hold_max_days = 14
    scan_frequency = "daily"
    max_position_usdc = 8.0
    min_ev_pp = MIN_VIOLATION_PP
    min_position_usdc = 2.0
    alert_only = True
    trading_enabled = False

    def _eligible(self, ev: dict) -> MarketInfo | None:
        vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
        if vol < MIN_VOLUME:
            return None
        days = _days_to_close(ev.get("endDate"))
        if days is None or days < MIN_DAYS_TO_CLOSE or days > MAX_DAYS_TO_CLOSE:
            return None
        price = _get_yes_price(ev)
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            return None
        title = ev.get("title") or ""
        stages = _extract_stages(title)
        if not stages:
            return None
        slug = ev.get("slug") or str(ev.get("id", ""))
        closes = (ev.get("endDate") or "")[:10]
        return MarketInfo(
            slug=slug, title=title, yes_price=price, volume=vol,
            days_to_close=days, closes=closes, url=event_url(ev),
            event=ev, stages=stages,
        )

    def _find_violations(self, markets: list[dict]) -> list[dict]:
        """Find pairs where downstream P(YES) > prerequisite P(YES)."""
        eligible = [info for ev in markets if (info := self._eligible(ev))]

        # Group by topic
        by_topic: dict[str, list[MarketInfo]] = {}
        for info in eligible:
            for key in _topic_keys(info.title):
                by_topic.setdefault(key, []).append(info)

        violations = []
        seen_pairs: set[tuple[str, str]] = set()

        for topic, group in sorted(by_topic.items(), key=lambda x: -len(x[1])):
            if len(group) < 2:
                continue
            # Check all pairs for prerequisite violations
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    pair_key = tuple(sorted([a.slug, b.slug]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    violation = self._check_pair(a, b, topic)
                    if violation:
                        violations.append(violation)

        # Sort by violation magnitude
        violations.sort(key=lambda v: v["violation_pp"], reverse=True)
        return violations

    def _check_pair(self, a: MarketInfo, b: MarketInfo, topic: str) -> dict | None:
        """Check if one market is a prerequisite of the other and prices violate logic."""
        # Find shared chain where one is earlier stage than the other
        for chain_a, stage_a in a.stages:
            for chain_b, stage_b in b.stages:
                if chain_a != chain_b:
                    continue
                if stage_a == stage_b:
                    continue
                # Earlier stage is the prerequisite
                if stage_a < stage_b:
                    prereq, downstream = a, b
                else:
                    prereq, downstream = b, a

                # Violation: downstream priced higher than prerequisite
                violation_pp = round((downstream.yes_price - prereq.yes_price) * 100, 1)
                if violation_pp < MIN_VIOLATION_PP:
                    continue

                return {
                    "topic": topic,
                    "prereq_slug": prereq.slug,
                    "prereq_title": prereq.title,
                    "prereq_price": prereq.yes_price,
                    "downstream_slug": downstream.slug,
                    "downstream_title": downstream.title,
                    "downstream_price": downstream.yes_price,
                    "violation_pp": violation_pp,
                    "prereq_closes": prereq.closes,
                    "downstream_closes": downstream.closes,
                    "downstream_url": downstream.url,
                    "downstream_days": downstream.days_to_close,
                    "downstream_event": downstream.event,
                }
        return None

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        violations = self._find_violations(markets)

        signals: list[Signal] = []
        for v in violations[:MAX_SIGNALS_PER_RUN]:
            downstream_no_price = 1.0 - v["downstream_price"]
            # P(NO on downstream) >= 1 - P(prereq) since downstream requires prereq
            p_no = 1.0 - v["prereq_price"]
            ev_pp = round((p_no - downstream_no_price) * 100, 1)

            self.last_check_details.append({
                "topic": v["topic"],
                "prereq": f"{v['prereq_title'][:40]} ({v['prereq_price']:.0%})",
                "downstream": f"{v['downstream_title'][:40]} ({v['downstream_price']:.0%})",
                "violation_pp": v["violation_pp"],
                "decision": "signal",
            })

            print(
                f"  [{self.name}] NO {v['downstream_title'][:44]} | "
                f"downstream={v['downstream_price']:.0%} > prereq={v['prereq_price']:.0%} | "
                f"violation={v['violation_pp']}pp | topic={v['topic']}"
            )
            signals.append(Signal(
                strategy=self.name,
                market_id=v["downstream_slug"],
                market_title=v["downstream_title"][:100],
                outcome="NO",
                market_price=round(v["downstream_price"], 4),
                p_hat=round(min(p_no, 0.99), 4),
                ev_pp=ev_pp,
                confidence="high",
                closes=v["downstream_closes"],
                url=v["downstream_url"],
                rationale=(
                    f"cond-prob:downstream({v['downstream_price']:.0%})>"
                    f"prereq({v['prereq_price']:.0%}),"
                    f"gap={v['violation_pp']}pp,"
                    f"topic={v['topic']}"
                ),
            ))

        # Log remaining violations as skipped
        for v in violations[MAX_SIGNALS_PER_RUN:]:
            self.last_check_details.append({
                "topic": v["topic"],
                "prereq": f"{v['prereq_title'][:40]} ({v['prereq_price']:.0%})",
                "downstream": f"{v['downstream_title'][:40]} ({v['downstream_price']:.0%})",
                "violation_pp": v["violation_pp"],
                "decision": "skip",
            })

        print(f"  [{self.name}] {len(signals)} signals from {len(violations)} violations")
        return signals

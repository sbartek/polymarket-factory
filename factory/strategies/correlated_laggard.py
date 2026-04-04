"""
Strategy: correlated_laggard
Hypothesis: Within clusters of clearly related markets, the most liquid market often
            reprices first and less-liquid peers can temporarily lag.
Method: Deterministic topic clustering + title-token overlap + liquidity ranking.
        This MVP is alert-only on purpose: it logs divergences for review but does not trade.
"""
from __future__ import annotations

import re
from datetime import date

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_VOLUME = 15_000
MIN_PRICE = 0.12
MAX_PRICE = 0.88
MAX_DAYS = 45
MIN_SHARED_TOKENS = 2
MIN_VOLUME_RATIO = 1.5
MIN_DIVERGENCE_PP = 18.0
MAX_ALERTS_PER_RUN = 5
TOPIC_STOPWORDS = {
    "will", "the", "this", "that", "with", "from", "have", "into", "after", "before",
    "over", "under", "than", "what", "when", "which", "could", "would", "market",
    "markets", "price", "prices", "polymarket", "reach", "hits", "hit", "end", "by",
    "for", "and", "its", "their", "they", "them", "year", "election",
}


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _tokenize(title: str) -> set[str]:
    tokens = set()
    for raw in re.findall(r"[a-z0-9]{3,}", (title or "").lower()):
        if raw.isdigit() or raw in TOPIC_STOPWORDS:
            continue
        tokens.add(raw)
    return tokens


class CorrelatedLaggardStrategy(Strategy):
    name = "correlated_laggard"
    alert_only = False
    trading_enabled = True
    promotable = True
    live_ready = False
    promotion_criteria = "docs/alert_only_graduation.md#promotion-criteria"
    edge_type = "stale_repricing"
    time_window = "short"
    target_hold_min_days = 1
    target_hold_max_days = 7
    scan_frequency = "3x/day"
    paused = False
    min_ev_pp = MIN_DIVERGENCE_PP
    last_check_details: list[dict] = []

    def _eligible(self, ev: dict) -> bool:
        volume = float(ev.get("volume24hr") or ev.get("volume") or 0)
        if volume < MIN_VOLUME:
            return False
        days = _days_to_close(ev.get("endDate"))
        if days is None or days < 0 or days > MAX_DAYS:
            return False
        price = get_yes_price(ev)
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            return False
        title = ev.get("title") or ""
        return len(_tokenize(title)) >= 3

    def _candidate_pairs(self, markets: list[dict]) -> tuple[dict[str, set[str]], list[dict]]:
        eligible = [ev for ev in markets if self._eligible(ev)]
        topic_groups: dict[str, set[str]] = {}
        candidates: list[dict] = []
        best_by_laggard: dict[str, dict] = {}
        for idx, left in enumerate(eligible):
            left_price = get_yes_price(left)
            left_volume = float(left.get("volume24hr") or left.get("volume") or 0)
            left_tokens = _tokenize(left.get("title") or "")
            if left_price is None:
                continue
            for right in eligible[idx + 1:]:
                right_price = get_yes_price(right)
                right_volume = float(right.get("volume24hr") or right.get("volume") or 0)
                right_tokens = _tokenize(right.get("title") or "")
                if right_price is None:
                    continue
                shared = left_tokens & right_tokens
                if len(shared) < MIN_SHARED_TOKENS:
                    continue
                topic_key = " ".join(sorted(shared)[:3])
                topic_groups.setdefault(topic_key, set()).update({
                    str(left.get("slug", "") or left.get("id", "")),
                    str(right.get("slug", "") or right.get("id", "")),
                })
                if left_volume >= right_volume:
                    leader, laggard = left, right
                    leader_price, laggard_price = left_price, right_price
                    leader_volume, laggard_volume = left_volume, right_volume
                else:
                    leader, laggard = right, left
                    leader_price, laggard_price = right_price, left_price
                    leader_volume, laggard_volume = right_volume, left_volume
                volume_ratio = leader_volume / max(laggard_volume, 1.0)
                divergence_pp = abs(leader_price - laggard_price) * 100
                decision = "watch"
                reason = "insufficient_divergence"
                if volume_ratio >= MIN_VOLUME_RATIO and divergence_pp >= MIN_DIVERGENCE_PP:
                    decision = "alert"
                    reason = "leader_move_not_fully_reflected"
                laggard_slug = str(laggard.get("slug", "") or laggard.get("id", ""))
                candidate = {
                    "topic_key": topic_key,
                    "leader": leader,
                    "laggard": laggard,
                    "leader_price": leader_price,
                    "laggard_price": laggard_price,
                    "leader_volume": leader_volume,
                    "laggard_volume": laggard_volume,
                    "volume_ratio": volume_ratio,
                    "shared_tokens": sorted(shared),
                    "divergence_pp": divergence_pp,
                    "decision": decision,
                    "reason": reason,
                }
                current = best_by_laggard.get(laggard_slug)
                if current is None or candidate["divergence_pp"] > current["divergence_pp"]:
                    best_by_laggard[laggard_slug] = candidate
        candidates = list(best_by_laggard.values())
        candidates.sort(key=lambda row: (row["decision"] != "alert", -row["divergence_pp"], -row["volume_ratio"]))
        return topic_groups, candidates

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        topic_groups, candidates = self._candidate_pairs(markets)
        signals: list[Signal] = []

        print(f"  [{self.name}] {len(topic_groups)} topic groups → {len(candidates)} leader/follower checks...")
        for row in candidates:
            leader = row["leader"]
            laggard = row["laggard"]
            leader_slug = str(leader.get("slug", "") or leader.get("id", ""))
            laggard_slug = str(laggard.get("slug", "") or laggard.get("id", ""))
            self.last_check_details.append({
                "leader_slug": leader_slug,
                "laggard_slug": laggard_slug,
                "topic_key": row["topic_key"],
                "leader_price": round(row["leader_price"], 4),
                "laggard_price": round(row["laggard_price"], 4),
                "divergence_pp": round(row["divergence_pp"], 1),
                "volume_ratio": round(row["volume_ratio"], 2),
                "decision": row["decision"],
                "reason": row["reason"],
            })
            if row["decision"] != "alert" or len(signals) >= MAX_ALERTS_PER_RUN:
                continue

            laggard_price = row["laggard_price"]
            leader_price = row["leader_price"]
            if leader_price >= laggard_price:
                outcome = "YES"
                market_price = laggard_price
                p_hat = max(leader_price, laggard_price)
            else:
                outcome = "NO"
                market_price = 1 - laggard_price
                p_hat = max(1 - leader_price, 1 - laggard_price)

            shared = ",".join(row["shared_tokens"][:4])
            signals.append(Signal(
                strategy=self.name,
                market_id=laggard_slug,
                market_title=(laggard.get("title") or "?")[:100],
                outcome=outcome,
                market_price=round(market_price, 4),
                p_hat=round(min(max(p_hat, market_price), 0.98), 4),
                ev_pp=round(row["divergence_pp"], 1),
                confidence="medium" if row["divergence_pp"] < 25 else "high",
                closes=(laggard.get("endDate") or "")[:10],
                url=event_url(laggard),
                rationale=(
                    f"alert_only:leader={leader_slug}:topic={row['topic_key']}:"
                    f"shared={shared}:vol_ratio={row['volume_ratio']:.2f}"
                )[:180],
            ))

        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

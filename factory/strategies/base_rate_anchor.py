"""
Strategy: base_rate_anchor
Hypothesis: New Polymarket markets often open near 50c regardless of the
historical base rate for that event type. Using kNN over resolved market
titles, we estimate the base rate and fade the mispricing.

Uses TF-IDF + cosine similarity over thousands of resolved market titles.
No LLM needed — pure statistical edge.
"""
from __future__ import annotations

import json
from datetime import date

from ..base_rate_index import BaseRateIndex
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_VOLUME = 5_000
MIN_PRICE = 0.15
MAX_PRICE = 0.85
MAX_DAYS_TO_CLOSE = 14
MIN_DAYS_TO_CLOSE = 0
MAX_SIGNALS_PER_RUN = 3
MIN_GAP_PP = 15.0      # minimum |base_rate - price| to trigger
MIN_NEIGHBORS = 5       # need enough data for confidence
MIN_AVG_SIMILARITY = 0.05  # neighbors must be somewhat relevant


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


class BaseRateAnchorStrategy(Strategy):
    name = "base_rate_anchor"
    last_check_details: list[dict] = []
    edge_type = "statistical_fade"
    time_window = "short"
    target_hold_min_days = 0
    target_hold_max_days = 14
    scan_frequency = "daily"
    max_position_usdc = 8.0
    min_ev_pp = MIN_GAP_PP
    min_position_usdc = 2.0
    alert_only = True
    trading_enabled = False

    _index: BaseRateIndex | None = None

    def _get_index(self) -> BaseRateIndex:
        if self._index is None:
            self._index = BaseRateIndex.load()
        return self._index

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        index = self._get_index()

        if index.size < 100:
            print(f"  [{self.name}] index too small ({index.size} entries), skipping. Run backfill_base_rates.py first.")
            return []

        candidates = []
        for ev in markets:
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or days < MIN_DAYS_TO_CLOSE or days > MAX_DAYS_TO_CLOSE:
                continue
            price = get_yes_price(ev)
            if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                continue

            title = ev.get("title") or ""
            slug = ev.get("slug") or str(ev.get("id", ""))
            if not title:
                continue

            result = index.query_base_rate(title, k=10)
            if result["n_neighbors"] < MIN_NEIGHBORS:
                continue

            avg_sim = sum(n["similarity"] for n in result["neighbors"]) / result["n_neighbors"]
            if avg_sim < MIN_AVG_SIMILARITY:
                continue

            base_rate = result["base_rate"]
            gap_pp = round((base_rate - price) * 100, 1)

            self.last_check_details.append({
                "slug": slug,
                "title": title[:50],
                "price": round(price, 3),
                "base_rate": base_rate,
                "gap_pp": gap_pp,
                "n_neighbors": result["n_neighbors"],
                "avg_similarity": round(avg_sim, 3),
                "decision": "signal" if abs(gap_pp) >= MIN_GAP_PP else "skip",
            })

            if abs(gap_pp) >= MIN_GAP_PP:
                candidates.append({
                    "slug": slug,
                    "title": title,
                    "price": price,
                    "base_rate": base_rate,
                    "gap_pp": gap_pp,
                    "abs_gap": abs(gap_pp),
                    "days": days,
                    "closes": (ev.get("endDate") or "")[:10],
                    "url": event_url(ev),
                    "neighbors": result["neighbors"][:3],
                    "avg_similarity": avg_sim,
                })

        # Sort by gap magnitude, take top N
        candidates.sort(key=lambda c: c["abs_gap"], reverse=True)
        selected = candidates[:MAX_SIGNALS_PER_RUN]

        signals: list[Signal] = []
        for c in selected:
            # Positive gap = base_rate > price → market underpriced → YES
            # Negative gap = base_rate < price → market overpriced → NO
            if c["gap_pp"] > 0:
                outcome = "YES"
                market_price = c["price"]
                p_hat = c["base_rate"]
            else:
                outcome = "NO"
                market_price = 1.0 - c["price"]
                p_hat = 1.0 - c["base_rate"]

            neighbor_summary = "; ".join(
                f"{n['title'][:30]}={'Y' if n['resolved_yes'] else 'N'}"
                for n in c["neighbors"]
            )

            print(
                f"  [{self.name}] {outcome} {c['title'][:44]} | "
                f"price={c['price']:.0%} base_rate={c['base_rate']:.0%} gap={c['gap_pp']:+.0f}pp | "
                f"{c['avg_similarity']:.2f} avg_sim"
            )
            signals.append(Signal(
                strategy=self.name,
                market_id=c["slug"],
                market_title=c["title"][:100],
                outcome=outcome,
                market_price=round(market_price, 4),
                p_hat=round(min(max(p_hat, 0.01), 0.99), 4),
                ev_pp=round(abs(c["gap_pp"]), 1),
                confidence="medium",
                closes=c["closes"],
                url=c["url"],
                rationale=f"base-rate:{c['base_rate']:.0%} vs mkt:{c['price']:.0%},gap={c['gap_pp']:+.0f}pp,nn={neighbor_summary[:120]}",
            ))

        print(f"  [{self.name}] {len(signals)} signals (index={index.size}, checked={len(self.last_check_details)})")
        return signals

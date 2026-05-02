"""
Strategy: expiry_convergence_buy
Hypothesis: Markets within 3-7 days of expiry where the leading outcome is
            priced 75-92% carry a "resolution uncertainty discount". As the
            clock ticks down, these prices converge toward 95-99%. This is a
            time-decay trade: harvesting the last few cents of repricing as
            uncertainty collapses.
Method: Deterministic — filter for near-expiry markets with stable high-
        probability leaders. No LLM, no external API.
Status: PAPER TRADING — promoted 2026-05-02 after 76 signals over 16 days.
"""
from __future__ import annotations

import json
from datetime import date

from ..db import FactoryDB
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_PRICE = 0.75
MAX_PRICE = 0.92
MIN_DAYS = 3
MAX_DAYS = 7
MIN_VOLUME = 2_000
MIN_STABILITY_CHECKS = 2  # must be leader in >=2 recent observations
MAX_ALERTS_PER_RUN = 5
TARGET_PRICE = 0.95  # expected convergence target

# Exclude categories with volatile near-expiry behavior
EXCLUDED_KEYWORDS = [
    " vs ", " vs. ",
    "nba", "nhl", "nfl", "mlb", "mls", "ipl", "ufc",
    "cricket", "tennis", "atp", "wta", "boxing", "esport",
    "league of legends", "lol:", "dota", "valorant", "cs2:",
    "grand prix", "formula",
    "temperature", "highest temp", "lowest temp", "weather",
    "bo3", "bo5", "game 1", "game 2", "game 3",
    "total kills", "over/under", "spread:",
    "up or down",
    "o/u ", "rounds",
]


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _is_excluded(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EXCLUDED_KEYWORDS)


class ExpiryConvergenceBuyStrategy(Strategy):
    name = "expiry_convergence_buy"
    edge_type = "stale_repricing"
    time_window = "short"
    target_hold_min_days = 1
    target_hold_max_days = 7
    scan_frequency = "3x/day"
    max_position_usdc = 5.0
    min_ev_pp = 5.0
    alert_only = False
    trading_enabled = True
    promotable = True
    promotion_criteria = "20 signals with >70% reaching 95c+ by expiry"
    signal_cooldown_hours = 24.0
    last_check_details: list[dict] = []

    def _check_price_stability(self, market_id: str, current_price: float, db: FactoryDB) -> bool:
        """Check if this market has been at a high price in recent observations."""
        try:
            with db._conn() as (conn, cur):
                cur.execute(
                    """
                    SELECT yes_price FROM market_observations
                    WHERE market_id = %s
                    ORDER BY created_at DESC LIMIT 6
                    """,
                    (market_id,),
                )
                rows = cur.fetchall()
                if len(rows) < MIN_STABILITY_CHECKS:
                    return False
                # Check: price has been >= 70% in at least MIN_STABILITY_CHECKS observations
                high_count = sum(1 for r in rows if float(r[0]) >= 0.70)
                return high_count >= MIN_STABILITY_CHECKS
        except Exception:
            return False

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []

        try:
            db = FactoryDB()
        except Exception:
            db = None

        candidates = []
        for ev in markets:
            title = ev.get("title") or ""
            if not title or _is_excluded(title):
                continue

            days = _days_to_close(ev.get("endDate"))
            if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
                continue

            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue

            price = get_yes_price(ev)
            if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                continue

            slug = ev.get("slug") or str(ev.get("id", ""))

            # Check price stability — must have been high for multiple observations
            if db and not self._check_price_stability(slug, price, db):
                self.last_check_details.append({
                    "market_slug": slug, "title": title[:80],
                    "price": round(price, 4), "days": days,
                    "decision": "skip", "reason": "unstable_price",
                })
                continue

            ev_pp = round((TARGET_PRICE - price) * 100, 1)
            if ev_pp < self.min_ev_pp:
                continue

            candidates.append({
                "slug": slug, "title": title, "price": price,
                "days": days, "volume": vol, "ev_pp": ev_pp,
                "closes": (ev.get("endDate") or "")[:10],
                "url": event_url(ev),
            })

            self.last_check_details.append({
                "market_slug": slug, "title": title[:80],
                "price": round(price, 4), "days": days,
                "ev_pp": ev_pp, "volume": vol,
                "decision": "alert", "reason": "expiry_convergence",
            })

        # Sort by EV (biggest discount first), then by days (closest expiry)
        candidates.sort(key=lambda c: (-c["ev_pp"], c["days"]))
        selected = candidates[:MAX_ALERTS_PER_RUN]

        signals = []
        for c in selected:
            print(
                f"  [{self.name}] YES {c['title'][:44]} | "
                f"price={c['price']:.0%} target={TARGET_PRICE:.0%} "
                f"ev={c['ev_pp']}pp | {c['days']}d to close"
            )
            signals.append(Signal(
                strategy=self.name,
                market_id=c["slug"],
                market_title=c["title"][:100],
                outcome="YES",
                market_price=round(c["price"], 4),
                p_hat=round(TARGET_PRICE, 4),
                ev_pp=c["ev_pp"],
                confidence="high" if c["ev_pp"] >= 10 else "medium",
                closes=c["closes"],
                url=c["url"],
                rationale=(
                    f"expiry_convergence:{c['price']:.0%}→{TARGET_PRICE:.0%},"
                    f"{c['days']}d,vol=${c['volume']:.0f}"
                ),
            ))

        print(f"  [{self.name}] {len(signals)} alerts from {len(candidates)} candidates")
        return signals

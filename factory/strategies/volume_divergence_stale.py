"""
Strategy: volume_divergence_stale
Hypothesis: When a market has a volume spike but NO price movement, while a correlated
            sibling market has moved, the stale market is likely to reprice.
Method: Three confirming signals:
        1. Volume anomaly — 24h volume > 2x the market's typical volume
        2. Price staleness — price barely moved despite the volume (<3pp in last 6h)
        3. Correlation confirmation — a related market (same topic) DID move significantly (>8pp)
        Direction: if correlated market went UP, bet YES on stale market; if DOWN, bet NO.
"""
from __future__ import annotations

from datetime import date

from ..db import FactoryDB
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy
from .correlated_laggard import EXCLUDED_CATEGORY_KEYWORDS, _tokenize

# ── Eligibility filters ──────────────────────────────────────────────
MIN_VOLUME = 10_000
MIN_PRICE = 0.10
MAX_PRICE = 0.88
MAX_DAYS = 45

# ── Token matching (stricter than correlated_laggard) ─────────────────
MIN_SHARED_TOKENS = 3
MIN_JACCARD = 0.30

# ── Signal thresholds ────────────────────────────────────────────────
MIN_VOLUME_RATIO = 2.0        # 24h vol vs typical (prev observation)
STALE_MOVE_THRESHOLD = 0.03   # <3pp move in last 6h → "stale"
MOVER_MOVE_THRESHOLD = 0.08   # >8pp move in last 6h → "mover"
MAX_ALERTS_PER_RUN = 3


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _slug(ev: dict) -> str:
    return str(ev.get("slug", "") or ev.get("id", ""))


class VolumeDivergenceStaleStrategy(Strategy):
    name = "volume_divergence_stale"
    alert_only = True
    trading_enabled = False
    promotable = True
    live_ready = False
    promotion_criteria = "20 signals with >55% reversion within 24h"
    edge_type = "combined_signal"
    time_window = "short"
    target_hold_min_days = 0.5
    target_hold_max_days = 7
    scan_frequency = "3x/day"
    paused = False
    min_ev_pp = 8.0
    signal_cooldown_hours = 24.0
    last_check_details: list[dict] = []

    # ── helpers ───────────────────────────────────────────────────────

    def _eligible(self, ev: dict) -> bool:
        title = ev.get("title") or ""
        title_lower = title.lower()
        if any(kw in title_lower for kw in EXCLUDED_CATEGORY_KEYWORDS):
            return False
        volume = float(ev.get("volume24hr") or ev.get("volume") or 0)
        if volume < MIN_VOLUME:
            return False
        days = _days_to_close(ev.get("endDate"))
        if days is None or days < 0 or days > MAX_DAYS:
            return False
        price = get_yes_price(ev)
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            return False
        return len(_tokenize(title)) >= 3

    def _build_move_lookup(self) -> dict[str, dict]:
        """
        Query DB for recent price observations and build a lookup:
        market_id -> {cur_price, prev_price, price_move, volume_24hr, ...}
        Includes ALL markets (even those with small moves) so we can identify
        both movers (>8pp) and stale markets (<3pp).
        """
        db = FactoryDB()
        # Get all moves (min_move=0.0 to capture stale markets too)
        # We use a small threshold to still get stale ones
        moves = db.get_recent_price_moves(min_move=0.0, max_hours=6.0)
        lookup: dict[str, dict] = {}
        for row in moves:
            mid = row.get("market_id") or row.get("market_slug") or ""
            if mid:
                lookup[mid] = row
        return lookup

    # ── scan ──────────────────────────────────────────────────────────

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []

        eligible = [ev for ev in markets if self._eligible(ev)]
        print(f"  [{self.name}] {len(eligible)} eligible markets")

        # Build move lookup from DB observations
        move_lookup = self._build_move_lookup()
        if not move_lookup:
            print(f"  [{self.name}] no recent observations in DB — skipping")
            return []

        # Index eligible markets by slug for fast lookup
        slug_to_ev: dict[str, dict] = {}
        slug_to_tokens: dict[str, set[str]] = {}
        for ev in eligible:
            s = _slug(ev)
            slug_to_ev[s] = ev
            slug_to_tokens[s] = _tokenize(ev.get("title") or "")

        # Find pairs: one stale + one mover
        signals: list[Signal] = []
        seen_stale: set[str] = set()
        slugs = list(slug_to_ev.keys())

        candidates: list[dict] = []
        for i, left_slug in enumerate(slugs):
            left_tokens = slug_to_tokens[left_slug]
            for right_slug in slugs[i + 1:]:
                right_tokens = slug_to_tokens[right_slug]

                # Token overlap check
                shared = left_tokens & right_tokens
                if len(shared) < MIN_SHARED_TOKENS:
                    continue
                smaller = min(len(left_tokens), len(right_tokens))
                if smaller == 0 or len(shared) / smaller < MIN_JACCARD:
                    continue

                # Look up price moves from DB for both markets
                # Markets might be keyed by market_id (numeric) or slug
                left_ev = slug_to_ev[left_slug]
                right_ev = slug_to_ev[right_slug]

                # Try to find observations by market_id from the event's markets list
                left_move_data = self._find_move_data(left_ev, move_lookup)
                right_move_data = self._find_move_data(right_ev, move_lookup)

                if left_move_data is None or right_move_data is None:
                    continue

                left_abs_move = abs(left_move_data.get("price_move", 0) or 0)
                right_abs_move = abs(right_move_data.get("price_move", 0) or 0)

                # Identify stale vs mover
                stale_slug = mover_slug = None
                stale_ev = mover_ev = None
                stale_move_data = mover_move_data = None

                if left_abs_move < STALE_MOVE_THRESHOLD and right_abs_move >= MOVER_MOVE_THRESHOLD:
                    stale_slug, mover_slug = left_slug, right_slug
                    stale_ev, mover_ev = left_ev, right_ev
                    stale_move_data, mover_move_data = left_move_data, right_move_data
                elif right_abs_move < STALE_MOVE_THRESHOLD and left_abs_move >= MOVER_MOVE_THRESHOLD:
                    stale_slug, mover_slug = right_slug, left_slug
                    stale_ev, mover_ev = right_ev, left_ev
                    stale_move_data, mover_move_data = right_move_data, left_move_data
                else:
                    continue

                # Volume anomaly check on the stale market
                stale_vol_24h = float(stale_ev.get("volume24hr") or stale_ev.get("volume") or 0)
                stale_prev_vol = float(stale_move_data.get("volume_24hr") or stale_move_data.get("volume") or 0)
                # Use the previous observation's volume as "typical" baseline
                # If no previous volume data, use current as fallback (skip)
                if stale_prev_vol <= 0:
                    continue
                volume_ratio = stale_vol_24h / stale_prev_vol
                if volume_ratio < MIN_VOLUME_RATIO:
                    continue

                # Calculate expected repricing direction and EV
                mover_price_move = mover_move_data.get("price_move", 0) or 0
                stale_price = get_yes_price(stale_ev)
                if stale_price is None:
                    continue

                # EV estimate: the stale market should reprice by at least
                # a fraction of the mover's move
                ev_pp = abs(mover_price_move) * 100  # full mover move as upper bound
                if ev_pp < self.min_ev_pp:
                    continue

                topic_key = " ".join(sorted(shared)[:3])

                candidates.append({
                    "stale_slug": stale_slug,
                    "mover_slug": mover_slug,
                    "stale_ev": stale_ev,
                    "mover_ev": mover_ev,
                    "stale_price": stale_price,
                    "mover_price_move": mover_price_move,
                    "volume_ratio": volume_ratio,
                    "stale_abs_move": left_abs_move if stale_slug == left_slug else right_abs_move,
                    "mover_abs_move": abs(mover_price_move),
                    "ev_pp": ev_pp,
                    "topic_key": topic_key,
                    "shared_tokens": sorted(shared),
                })

        # Sort by EV descending
        candidates.sort(key=lambda c: -c["ev_pp"])

        for row in candidates:
            stale_slug = row["stale_slug"]
            if stale_slug in seen_stale:
                continue

            self.last_check_details.append({
                "stale_slug": stale_slug,
                "mover_slug": row["mover_slug"],
                "topic_key": row["topic_key"],
                "stale_price": round(row["stale_price"], 4),
                "mover_price_move": round(row["mover_price_move"], 4),
                "volume_ratio": round(row["volume_ratio"], 2),
                "stale_abs_move": round(row["stale_abs_move"], 4),
                "mover_abs_move": round(row["mover_abs_move"], 4),
                "ev_pp": round(row["ev_pp"], 1),
                "decision": "alert",
                "reason": "volume_spike_stale_correlated_mover",
            })

            if len(signals) >= MAX_ALERTS_PER_RUN:
                continue

            stale_price = row["stale_price"]
            mover_price_move = row["mover_price_move"]

            # Direction: if correlated market went UP, bet YES on stale; if DOWN, bet NO
            if mover_price_move > 0:
                outcome = "YES"
                market_price = stale_price
                p_hat = min(stale_price + abs(mover_price_move), 0.98)
            else:
                outcome = "NO"
                market_price = 1 - stale_price
                p_hat = min((1 - stale_price) + abs(mover_price_move), 0.98)

            shared = ",".join(row["shared_tokens"][:4])
            signals.append(Signal(
                strategy=self.name,
                market_id=stale_slug,
                market_title=(row["stale_ev"].get("title") or "?")[:100],
                outcome=outcome,
                market_price=round(market_price, 4),
                p_hat=round(max(p_hat, market_price + 0.01), 4),
                ev_pp=round(row["ev_pp"], 1),
                confidence="medium" if row["ev_pp"] < 15 else "high",
                closes=(row["stale_ev"].get("endDate") or "")[:10],
                url=event_url(row["stale_ev"]),
                rationale=(
                    f"alert_only:mover={row['mover_slug']}:topic={row['topic_key']}:"
                    f"shared={shared}:vol_ratio={row['volume_ratio']:.1f}:"
                    f"mover_move={row['mover_price_move']:+.2f}"
                )[:180],
            ))
            seen_stale.add(stale_slug)

        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

    @staticmethod
    def _find_move_data(ev: dict, move_lookup: dict[str, dict]) -> dict | None:
        """Try to find observation data for an event by market_id or slug."""
        # Try by sub-market ids first
        for m in ev.get("markets", []):
            mid = str(m.get("id", ""))
            if mid and mid in move_lookup:
                return move_lookup[mid]
        # Try by event slug
        slug = _slug(ev)
        if slug and slug in move_lookup:
            return move_lookup[slug]
        # Try by market_slug
        for m in ev.get("markets", []):
            ms = str(m.get("slug", ""))
            if ms and ms in move_lookup:
                return move_lookup[ms]
        return None

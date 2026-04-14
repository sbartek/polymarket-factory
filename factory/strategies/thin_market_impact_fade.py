"""
Strategy: thin_market_impact_fade
Hypothesis: When a single large order hits a thin Polymarket book (liquidity < $5k),
            it can move the price 15-30% temporarily. This is transient market impact,
            not information. Once the impact order is absorbed, the price mean-reverts.
Method: Query market_observations for recent large price moves, cross-reference with
        current liquidity data, and fade moves on thin books that are not near resolution.
Status: ALERT-ONLY — collecting data for promotion evaluation.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..db import FactoryDB
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_PRICE_MOVE = 0.12   # 12pp minimum move to consider
MAX_HOURS = 4.0          # look back window
MAX_LIQUIDITY = 5_000    # only thin books ($5k or less)
MIN_DAYS_TO_CLOSE = 3    # exclude markets near resolution
MIN_PRICE = 0.10         # avoid near-zero/near-one markets
MAX_PRICE = 0.90
MAX_ALERTS_PER_RUN = 4

# Exclude sports/esports/weather — same list as correlated_laggard
EXCLUDED_CATEGORY_KEYWORDS = [
    "temperature", "highest temp", "lowest temp", "weather",
    " vs ", " vs. ",
    "bo3", "bo5",
    "nba", "nhl", "nfl", "mlb", "mls", "ipl", "ufc",
    "cricket", "tennis", "atp", "wta", "boxing", "esport",
    "league of legends", "lol:", "dota", "valorant", "cs2:",
    "grand prix", "formula",
]

UTC = timezone.utc


def _days_to_close(close_time: str | None) -> int | None:
    if not close_time:
        return None
    try:
        return (date.fromisoformat(close_time[:10]) - date.today()).days
    except ValueError:
        return None


def _is_excluded(title: str) -> bool:
    title_lower = (title or "").lower()
    return any(kw in title_lower for kw in EXCLUDED_CATEGORY_KEYWORDS)


class ThinMarketImpactFadeStrategy(Strategy):
    name = "thin_market_impact_fade"
    alert_only = False
    trading_enabled = True
    promotable = True
    live_ready = False
    promotion_criteria = "20 signals with >55% reversion within 6h — PROMOTED 2026-04-14 at 77% accuracy (20/26)"
    edge_type = "structural"
    time_window = "intraday"
    target_hold_min_days = 0.1
    target_hold_max_days = 2
    scan_frequency = "3x/day"
    max_position_usdc = 8.0
    min_ev_pp = 12.0
    signal_cooldown_hours = 6.0
    last_check_details: list[dict] = []

    def _get_moves_with_liquidity(self, db: FactoryDB) -> list[dict]:
        """Query recent price moves including liquidity from market_observations."""
        cutoff = (datetime.now(UTC) - timedelta(hours=MAX_HOURS)).isoformat(timespec="seconds")
        query = """
            WITH ranked AS (
                SELECT market_id, market_slug, market_title, yes_price, liquidity,
                       volume, volume_24hr, close_time, created_at,
                       ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY created_at DESC) as rn
                FROM market_observations
                WHERE yes_price IS NOT NULL AND created_at >= %s
            )
            SELECT
                cur.market_id, cur.market_slug, cur.market_title,
                cur.yes_price AS cur_price, prev.yes_price AS prev_price,
                cur.yes_price - prev.yes_price AS price_move,
                cur.liquidity, cur.volume, cur.volume_24hr, cur.close_time,
                cur.created_at AS cur_time, prev.created_at AS prev_time
            FROM ranked cur
            JOIN ranked prev ON cur.market_id = prev.market_id AND prev.rn = 2
            WHERE cur.rn = 1
              AND ABS(cur.yes_price - prev.yes_price) >= %s
            ORDER BY ABS(cur.yes_price - prev.yes_price) DESC
        """
        with db._conn() as (conn, cur):
            cur.execute(query, (cutoff, MIN_PRICE_MOVE))
            return [dict(r) for r in cur.fetchall()]

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        db = FactoryDB()

        # Build lookup from current market snapshot for URL/metadata
        market_lookup: dict[str, dict] = {}
        for ev in markets:
            slug = ev.get("slug") or ""
            if slug:
                market_lookup[slug] = ev

        moves = self._get_moves_with_liquidity(db)
        signals: list[Signal] = []
        seen_market_ids: set[str] = set()

        for move in moves:
            market_id = move["market_id"]
            price_move = move["price_move"]
            cur_price = move["cur_price"]
            liquidity = move.get("liquidity") or 0
            volume = move.get("volume") or move.get("volume_24hr") or 0
            title = move.get("market_title") or market_id

            # Dedup by market_id
            if market_id in seen_market_ids:
                continue
            seen_market_ids.add(market_id)

            # Filter: exclude sports/esports/weather
            if _is_excluded(title):
                continue

            # Filter: price in tradeable range
            if cur_price < MIN_PRICE or cur_price > MAX_PRICE:
                continue

            # Filter: thin book only
            if liquidity <= 0 or liquidity > MAX_LIQUIDITY:
                continue

            # Filter: not near resolution (>3 days to close)
            days = _days_to_close(move.get("close_time"))
            if days is None or days < MIN_DAYS_TO_CLOSE:
                continue

            # Filter: moderate volume spike — not sustained high flow
            # If 24h volume is very high relative to liquidity, it's sustained flow, skip
            vol_24hr = move.get("volume_24hr") or 0
            if vol_24hr > 0 and liquidity > 0 and vol_24hr / liquidity > 20:
                continue

            # Fade the move: if price went up, bet NO; if down, bet YES
            if price_move > 0:
                outcome = "NO"
                # We think YES is overpriced, fair value is closer to prev_price
                p_hat = round(1 - move["prev_price"], 4)
                market_price = round(1 - cur_price, 4)
            else:
                outcome = "YES"
                p_hat = round(move["prev_price"], 4)
                market_price = round(cur_price, 4)

            ev_pp = (p_hat - market_price) * 100
            if ev_pp < self.min_ev_pp:
                continue

            # Get event URL from market snapshot
            ev = market_lookup.get(market_id, {})
            url = event_url(ev) if ev else ""

            self.last_check_details.append({
                "market_slug": market_id,
                "title": title[:80],
                "price_move": round(price_move, 4),
                "cur_price": cur_price,
                "prev_price": move["prev_price"],
                "liquidity": liquidity,
                "volume_24hr": vol_24hr,
                "days_to_close": days,
                "decision": "alert",
                "reason": f"thin book fade {price_move:+.2f} on liq=${liquidity:.0f}",
            })

            signals.append(Signal(
                strategy=self.name,
                market_id=market_id,
                market_title=title[:100],
                outcome=outcome,
                market_price=market_price,
                p_hat=p_hat,
                ev_pp=round(ev_pp, 1),
                confidence="medium",
                closes=(move.get("close_time") or "")[:10],
                url=url,
                rationale=(
                    f"thin_impact_fade:{price_move:+.2f}pp|liq=${liquidity:.0f}"
                    f"|vol24h=${vol_24hr:.0f}|{move.get('cur_time', '?')[:16]}"
                ),
            ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(moves)} moves found, {len(signals)} alerts")
        return signals

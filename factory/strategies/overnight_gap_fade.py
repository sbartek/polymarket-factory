"""
Strategy: overnight_gap_fade
Thesis: During low-liquidity overnight hours (01:00-08:00 UTC), small orders can
move Polymarket prices disproportionately. These moves often revert when liquidity
returns during US/EU trading hours. Fade overnight price moves that aren't backed
by proportional volume.
"""
from datetime import UTC, datetime, timedelta

from ..db import FactoryDB
from ..feed import event_url
from ..models import Signal
from .base import Strategy

# Overnight window: only scan during early US morning to catch reversion
SCAN_HOUR_START = 8   # UTC
SCAN_HOUR_END = 12    # UTC

# Observation lookback
LOOKBACK_HOURS_MIN = 6
LOOKBACK_HOURS_MAX = 8

# Signal filters
MIN_PRICE_MOVE_PP = 8.0     # minimum overnight move in percentage points
MAX_VOL_RATIO = 2.0         # vol_24hr must be < 2x typical to count as thin
TYPICAL_VOL_24HR = 50_000   # baseline "typical" 24h volume
MIN_LIQUIDITY = 2_000       # $2k minimum liquidity
MIN_PRICE = 0.08            # ignore extreme prices
MAX_PRICE = 0.92
MAX_SIGNALS_PER_RUN = 3

# Sports/esports keywords — legitimate overnight results, skip these
EXCLUDED_KEYWORDS = [
    " vs ", " vs. ", "nba", "nhl", "nfl", "mlb", "mls", "ipl",
    "cricket", "tennis", "atp", "wta", "ufc", "boxing", "premier league",
    "champions league", "serie a", "la liga", "bundesliga", "ligue 1",
    "esport", "valorant", "cs2", "counter-strike", "dota", "league of legends",
    "lol:", "bo3", "bo5",
]


def _is_excluded(title: str) -> bool:
    tl = title.lower()
    return any(kw in tl for kw in EXCLUDED_KEYWORDS)


class OvernightGapFadeStrategy(Strategy):
    name = "overnight_gap_fade"
    alert_only = True
    trading_enabled = False
    promotable = True
    promotion_criteria = "20 signals with >55% reversion within 12h"
    min_ev_pp = 8.0
    edge_type = "structural"
    time_window = "intraday"
    target_hold_min_days = 0.1
    target_hold_max_days = 1.0
    scan_frequency = "3x/day"
    max_position_usdc = 10.0
    signal_cooldown_hours = 12.0

    def scan(self, markets: list[dict]) -> list[Signal]:
        now = datetime.now(UTC)

        # Only run during the reversion window (08:00-12:00 UTC)
        if not (SCAN_HOUR_START <= now.hour < SCAN_HOUR_END):
            print(f"  [{self.name}] outside scan window ({SCAN_HOUR_START:02d}:00-{SCAN_HOUR_END:02d}:00 UTC), skipping")
            return []

        db = FactoryDB()

        # Query observations from the overnight window (~6-8h ago) and recent
        cutoff_old = (now - timedelta(hours=LOOKBACK_HOURS_MAX)).isoformat(timespec="seconds")
        cutoff_new = (now - timedelta(hours=LOOKBACK_HOURS_MIN)).isoformat(timespec="seconds")

        # Get earliest observations (overnight start) and latest (now-ish)
        query = """
            WITH old_obs AS (
                SELECT DISTINCT ON (market_id)
                    market_id, market_title, yes_price, volume_24hr, liquidity, created_at
                FROM market_observations
                WHERE created_at >= %s AND created_at <= %s
                  AND yes_price IS NOT NULL
                ORDER BY market_id, created_at ASC
            ),
            new_obs AS (
                SELECT DISTINCT ON (market_id)
                    market_id, yes_price, volume_24hr, liquidity, created_at
                FROM market_observations
                WHERE created_at >= %s
                  AND yes_price IS NOT NULL
                ORDER BY market_id, created_at DESC
            )
            SELECT
                o.market_id, o.market_title,
                o.yes_price AS old_price, n.yes_price AS new_price,
                n.yes_price - o.yes_price AS price_move,
                o.volume_24hr AS old_vol, n.volume_24hr AS new_vol,
                n.liquidity,
                o.created_at AS old_time, n.created_at AS new_time
            FROM old_obs o
            JOIN new_obs n ON o.market_id = n.market_id
            WHERE ABS(n.yes_price - o.yes_price) >= %s
            ORDER BY ABS(n.yes_price - o.yes_price) DESC
        """

        recent_cutoff = (now - timedelta(hours=1)).isoformat(timespec="seconds")
        min_move = MIN_PRICE_MOVE_PP / 100.0

        with db._conn() as (conn, cur):
            cur.execute(query, (cutoff_old, cutoff_new, recent_cutoff, min_move))
            rows = [dict(r) for r in cur.fetchall()]

        # Build a slug lookup from the markets feed
        slug_map: dict[str, dict] = {}
        for ev in markets:
            for m in ev.get("markets", []):
                mid = str(m.get("id", ""))
                if mid:
                    slug_map[mid] = ev

        signals: list[Signal] = []
        for row in rows:
            market_id = row["market_id"]
            title = row.get("market_title") or ""

            # Skip sports/esports
            if _is_excluded(title):
                continue

            new_price = float(row["new_price"])
            old_price = float(row["old_price"])
            price_move = float(row["price_move"])
            move_pp = abs(price_move) * 100

            # Skip extreme prices
            if not (MIN_PRICE <= new_price <= MAX_PRICE):
                continue

            # Volume filter: reject if volume spiked (legitimate move)
            new_vol = float(row.get("new_vol") or 0)
            if new_vol > MAX_VOL_RATIO * TYPICAL_VOL_24HR:
                continue

            # Liquidity filter
            liquidity = float(row.get("liquidity") or 0)
            if liquidity < MIN_LIQUIDITY:
                continue

            # Fade direction: if price went up overnight, bet NO (expect reversion down)
            if price_move > 0:
                outcome = "NO"
                # We're buying NO at (1 - new_price), expecting it to revert toward (1 - old_price)
                market_price = 1 - new_price
                p_hat = min(1 - old_price + 0.02, 0.95)  # conservative: don't expect full reversion
            else:
                outcome = "YES"
                market_price = new_price
                p_hat = min(old_price - 0.02, 0.95)  # conservative

            ev_pp = (p_hat - market_price) * 100
            if ev_pp < self.min_ev_pp:
                continue

            # Find the event for URL
            ev = slug_map.get(market_id, {})
            url = event_url(ev) if ev else ""

            confidence = "medium" if move_pp >= 12 else "low"

            signals.append(Signal(
                strategy=self.name,
                market_id=market_id,
                market_title=title[:100],
                outcome=outcome,
                market_price=round(market_price, 4),
                p_hat=round(p_hat, 4),
                ev_pp=round(ev_pp, 1),
                confidence=confidence,
                closes="",
                url=url,
                rationale=f"overnight_fade: {old_price*100:.0f}%→{new_price*100:.0f}% ({move_pp:+.0f}pp), vol_24h=${new_vol:,.0f}, liq=${liquidity:,.0f}",
            ))

            if len(signals) >= MAX_SIGNALS_PER_RUN:
                break

        print(f"  [{self.name}] {len(rows)} overnight movers found, {len(signals)} signals")
        return signals

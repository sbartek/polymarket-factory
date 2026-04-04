"""
Strategy: price_move_fade
Hypothesis: Large price moves (>15pp) on short-term binary markets that aren't
driven by news tend to be noise/thin-book artifacts that revert within 12-24h.
Method: Compare consecutive price snapshots from market_observations table.
Fade moves that exceed the threshold on markets closing within 7 days.
Status: ALERT-ONLY — accumulate signals before enabling paper trading.
"""
from __future__ import annotations

import json
from datetime import date

from ..db import FactoryDB
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MIN_PRICE_MOVE = 0.15  # 15pp minimum move
MAX_DAYS_TO_CLOSE = 7
MIN_VOLUME = 5_000
MIN_PRICE = 0.10       # avoid near-zero/near-one markets
MAX_PRICE = 0.90
MAX_ALERTS_PER_RUN = 5


def _days_to_close(close_time: str | None) -> int | None:
    if not close_time:
        return None
    try:
        return (date.fromisoformat(close_time[:10]) - date.today()).days
    except ValueError:
        return None


class PriceMoveFadeStrategy(Strategy):
    name = "price_move_fade"
    edge_type = "statistical_fade"
    time_window = "short"
    target_hold_min_days = 0.5
    target_hold_max_days = 7
    scan_frequency = "3x/day"
    max_position_usdc = 8.0
    min_ev_pp = 10.0
    alert_only = True
    trading_enabled = False
    promotable = True
    promotion_criteria = "20 alerts with >55% directional accuracy"
    last_check_details: list[dict] = []

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        db = FactoryDB()

        # Build lookup from current market snapshot for URL/metadata
        market_lookup: dict[str, dict] = {}
        for ev in markets:
            slug = ev.get("slug") or ""
            if slug:
                market_lookup[slug] = ev

        moves = db.get_recent_price_moves(min_move=MIN_PRICE_MOVE, max_hours=6.0)
        signals: list[Signal] = []

        for move in moves:
            market_id = move["market_id"]
            price_move = move["price_move"]
            cur_price = move["cur_price"]
            volume = move.get("volume") or move.get("volume_24hr") or 0

            # Filter: enough volume
            if volume < MIN_VOLUME:
                continue

            # Filter: price in tradeable range
            if cur_price < MIN_PRICE or cur_price > MAX_PRICE:
                continue

            # Filter: market closes within MAX_DAYS_TO_CLOSE
            days = _days_to_close(move.get("close_time"))
            if days is None or days < 0 or days > MAX_DAYS_TO_CLOSE:
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
            title = move.get("market_title") or market_id

            self.last_check_details.append({
                "market_slug": market_id,
                "title": title[:80],
                "price_move": round(price_move, 4),
                "cur_price": cur_price,
                "prev_price": move["prev_price"],
                "volume": volume,
                "days_to_close": days,
                "decision": "alert",
                "reason": f"fade {price_move:+.2f} on {title[:40]}",
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
                rationale=f"price_move_fade:{price_move:+.2f}pp in {move.get('cur_time', '?')[:16]}-{move.get('prev_time', '?')[:16]}",
            ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(moves)} moves found, {len(signals)} alerts")
        return signals

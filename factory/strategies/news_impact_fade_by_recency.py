"""
Strategy: news_impact_fade_by_recency
Hypothesis: Some public-news-driven price moves overshoot in the first hours
after publication, especially on liquid short-dated markets. We fade the move
only when there is recent, timestamped news attached to the moved market.

This is intentionally narrower than ev_news:
- no LLM
- requires a recent move from market_observations
- requires recent news hits from DDGS
- stays alert-only until there is evidence of useful reversion
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from ddgs import DDGS

from ..db import FactoryDB
from ..feed import event_url
from ..models import Signal
from .base import Strategy

MIN_PRICE_MOVE = 0.08
MIN_VOLUME = 5_000
MIN_PRICE = 0.10
MAX_PRICE = 0.90
MAX_DAYS_TO_CLOSE = 7
MAX_ALERTS_PER_RUN = 3
RECENT_NEWS_HOURS = 12
RECENT_NEWS_MIN_COUNT = 1


def _days_to_close(close_time: str | None) -> int | None:
    if not close_time:
        return None
    try:
        return (date.fromisoformat(close_time[:10]) - date.today()).days
    except ValueError:
        return None


def _parse_news_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    cleaned = raw.strip().replace("Z", "+00:00")
    for candidate in (cleaned, cleaned.replace(" GMT", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            continue
    return None


class NewsImpactFadeByRecencyStrategy(Strategy):
    name = "news_impact_fade_by_recency"
    edge_type = "information"
    time_window = "intraday"
    target_hold_min_days = 0.05
    target_hold_max_days = 1.0
    scan_frequency = "3x/day"
    max_position_usdc = 0.0
    min_position_usdc = 0.0
    min_ev_pp = 8.0
    alert_only = True
    trading_enabled = False
    promotable = True
    live_ready = False
    promotion_criteria = "25 alerts with >55% half-reversion within 6h of news-linked move"
    last_check_details: list[dict] = []

    def _fetch_news(self, query: str, n: int = 6) -> list[dict]:
        try:
            return list(DDGS(timeout=15).news(query, max_results=n))
        except Exception:
            return []

    def _news_recency(self, news: list[dict], now: datetime) -> tuple[int, float | None]:
        recent = 0
        latest_hours = None
        for item in news:
            published = _parse_news_time(item.get("date"))
            if not published:
                continue
            age_hours = max((now - published).total_seconds() / 3600, 0.0)
            if latest_hours is None or age_hours < latest_hours:
                latest_hours = age_hours
            if age_hours <= RECENT_NEWS_HOURS:
                recent += 1
        return recent, latest_hours

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        try:
            db = FactoryDB()
        except Exception:
            print(f"  [{self.name}] DB unavailable, 0 alerts")
            return []

        market_lookup = {}
        for ev in markets:
            slug = ev.get("slug") or ""
            if slug:
                market_lookup[slug] = ev

        moves = db.get_recent_price_moves(min_move=MIN_PRICE_MOVE, max_hours=6.0)
        now = datetime.now(UTC)
        candidates = []

        for move in moves:
            market_id = str(move["market_id"])
            title = move.get("market_title") or market_id
            volume = float(move.get("volume") or move.get("volume_24hr") or 0)
            cur_price = float(move["cur_price"])
            if volume < MIN_VOLUME:
                continue
            if cur_price < MIN_PRICE or cur_price > MAX_PRICE:
                continue
            days = _days_to_close(move.get("close_time"))
            if days is None or days < 0 or days > MAX_DAYS_TO_CLOSE:
                continue

            news = self._fetch_news(title, n=6)
            recent_count, latest_hours = self._news_recency(news, now)
            if recent_count < RECENT_NEWS_MIN_COUNT or latest_hours is None:
                continue

            candidates.append({
                "move": move,
                "title": title,
                "recent_count": recent_count,
                "latest_hours": latest_hours,
                "news": news,
            })

        candidates.sort(key=lambda row: (row["latest_hours"], -abs(row["move"]["price_move"])))
        signals: list[Signal] = []

        for row in candidates[:MAX_ALERTS_PER_RUN]:
            move = row["move"]
            price_move = float(move["price_move"])
            cur_price = float(move["cur_price"])
            prev_price = float(move["prev_price"])

            # Fade toward a half-reversion anchor, slightly stronger for fresher news.
            fade_weight = 0.55 if row["latest_hours"] <= 2 else 0.5
            expected_yes = min(max(cur_price - (price_move * fade_weight), 0.01), 0.99)

            if price_move > 0:
                outcome = "NO"
                market_price = round(1 - cur_price, 4)
                p_hat = round(1 - expected_yes, 4)
            else:
                outcome = "YES"
                market_price = round(cur_price, 4)
                p_hat = round(expected_yes, 4)

            ev_pp = round((p_hat - market_price) * 100, 1)
            if ev_pp < self.min_ev_pp:
                continue

            ev = market_lookup.get(str(move.get("market_slug") or market_id), {})
            url = event_url(ev) if ev else ""
            closes = (move.get("close_time") or "")[:10]

            self.last_check_details.append({
                "market_slug": market_id,
                "title": row["title"][:120],
                "price_move": round(price_move, 4),
                "recent_news_count": row["recent_count"],
                "latest_news_hours": round(row["latest_hours"], 2),
                "decision": "alert",
                "reason": "recent_news_linked_move",
            })

            signals.append(
                Signal(
                    strategy=self.name,
                    market_id=market_id,
                    market_title=row["title"][:100],
                    outcome=outcome,
                    market_price=market_price,
                    p_hat=p_hat,
                    ev_pp=ev_pp,
                    confidence="high" if row["latest_hours"] <= 2 else "medium",
                    closes=closes,
                    url=url,
                    rationale=f"news_fade:move={price_move:+.3f},recent_news={row['recent_count']},latest_h={row['latest_hours']:.2f},prev={prev_price:.3f},cur={cur_price:.3f}",
                )
            )

        print(f"  [{self.name}] {len(candidates)} news-linked moves, {len(signals)} alerts")
        return signals

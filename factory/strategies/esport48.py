"""
Strategy: esport48
Hypothesis: Near-expiry esport books can briefly overstate favorites or underprice the
other side when liquidity is decent but not deep enough for perfect repricing.
Method: Deterministic screener across all games. Filter to esport-tagged or clearly
game-specific markets closing within 48h, exclude dead books, then flag the cheaper
side with a small mean-reversion pull toward 50%.
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..feed import event_url, format_volume, get_yes_price
from ..models import Signal
from .base import Strategy

MAX_HOURS_TO_CLOSE = 48.0
MIN_VOLUME = 7_500
MIN_LIQUIDITY = 2_500
MIN_PRICE = 0.10
MAX_PRICE = 0.90
MIN_EDGE_PP = 6.0
MAX_ALERTS_PER_RUN = 5
ESPORT_TERMS = {
    "esport", "esports", "gaming", "valorant", "cs2", "counter strike", "counter-strike",
    "dota", "dota 2", "league of legends", "lol", "rocket league", "overwatch",
    "call of duty", "cod", "rainbow six", "apex", "fortnite", "starcraft", "pubg",
}
ROSTER_TERMS = {"roster", "lineup", "stand-in", "stand in", "substitute", "bench", "suspend", "ban"}
FORM_TERMS = {"match", "series", "map", "game", "final", "finals", "playoff", "streak", "upset", "sweep"}


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _hours_to_close(end_date: str | None) -> float | None:
    dt = _parse_dt(end_date)
    if not dt:
        return None
    return (dt - datetime.now(UTC)).total_seconds() / 3600


def _collect_text(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.lower()]
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            if k in {"name", "slug", "label", "title", "category", "ticker", "series"}:
                out.extend(_collect_text(v))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_collect_text(item))
        return out
    return []


def _event_text(ev: dict) -> str:
    chunks = _collect_text({
        "title": ev.get("title"),
        "slug": ev.get("slug"),
        "ticker": ev.get("ticker"),
        "category": ev.get("category"),
        "series": ev.get("series"),
        "tags": ev.get("tags"),
        "events": ev.get("events"),
    })
    return " | ".join(chunks)


def _is_esport_event(ev: dict) -> bool:
    text = _event_text(ev)
    return any(term in text for term in ESPORT_TERMS)


def _numeric_value(*values) -> float:
    for value in values:
        try:
            if value is None or value == "":
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _liquidity(ev: dict) -> float:
    market = ev.get("markets", [{}])[0] if ev.get("markets") else {}
    return max(
        _numeric_value(ev.get("liquidity"), ev.get("liquidityNum"), ev.get("liquidityClob")),
        _numeric_value(market.get("liquidity"), market.get("liquidityNum"), market.get("liquidityClob")),
    )


class Esport48Strategy(Strategy):
    name = "esport48"
    alert_only = True
    trading_enabled = False
    promotable = True
    live_ready = False
    promotion_criteria = "docs/alert_only_graduation.md#promotion-criteria"
    edge_type = "stale_repricing"
    time_window = "intraday"
    target_hold_min_days = 0.04
    target_hold_max_days = 2.0
    scan_frequency = "3x/day"
    paused = False
    min_ev_pp = MIN_EDGE_PP
    fast_dry_run_candidates = 6
    last_check_details: list[dict] = []

    def _eligible(self, ev: dict) -> dict | None:
        if not _is_esport_event(ev):
            return None

        price = get_yes_price(ev)
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            return None

        hours = _hours_to_close(ev.get("endDate"))
        if hours is None or hours <= 0 or hours > MAX_HOURS_TO_CLOSE:
            return None

        volume = _numeric_value(ev.get("volume24hr"), ev.get("volume"))
        liquidity = _liquidity(ev)
        if volume < MIN_VOLUME:
            return None
        if liquidity and liquidity < MIN_LIQUIDITY:
            return None

        return {
            "slug": str(ev.get("slug", "") or ev.get("id", "")),
            "title": ev.get("title") or "?",
            "price": price,
            "hours_to_close": hours,
            "volume": volume,
            "liquidity": liquidity,
            "url": event_url(ev),
            "closes": (ev.get("endDate") or "")[:10],
            "text": _event_text(ev),
        }

    def _signal_profile(self, candidate: dict) -> tuple[str, float, str, str]:
        price = candidate["price"]
        implied = price if price < 0.5 else 1 - price
        liquidity = candidate["liquidity"]
        volume = candidate["volume"]
        hours = candidate["hours_to_close"]

        pull = 0.03
        pull += min(abs(price - 0.5) * 0.35, 0.08)
        if volume >= 20_000:
            pull += 0.02
        if liquidity >= 8_000:
            pull += 0.02
        if hours <= 18:
            pull += 0.02

        subtype = "market_lag"
        if any(term in candidate["text"] for term in ROSTER_TERMS):
            subtype = "news/roster_edge"
        elif price <= 0.22 or price >= 0.78:
            subtype = "overreaction/underreaction_edge"
        elif any(term in candidate["text"] for term in FORM_TERMS):
            subtype = "form/momentum_edge"

        confidence_score = 0
        confidence_score += volume >= 15_000
        confidence_score += liquidity >= 5_000
        confidence_score += abs(price - 0.5) >= 0.18
        confidence_score += hours <= 24
        confidence = "high" if confidence_score >= 3 else "medium"

        outcome = "YES" if price < 0.5 else "NO"
        p_hat = min(implied + pull, 0.5)
        rationale = (
            f"{subtype}: {price*100:.0f}% YES, closes in {hours:.0f}h, "
            f"vol {format_volume(volume)}, liq {format_volume(liquidity)}"
        )
        return outcome, round(p_hat, 4), confidence, rationale[:180]

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []
        candidates = []
        for ev in markets:
            row = self._eligible(ev)
            if row:
                candidates.append(row)

        candidates.sort(
            key=lambda row: (
                -abs(row["price"] - 0.5),
                -row["liquidity"],
                -row["volume"],
                row["hours_to_close"],
            )
        )
        limit = getattr(self, "_fast_dry_run_candidates_override", None)
        if limit is not None:
            candidates = candidates[:limit]

        print(f"  [{self.name}] {len(candidates)} esport candidates within {MAX_HOURS_TO_CLOSE:.0f}h...")
        signals: list[Signal] = []
        seen_market_ids: set[str] = set()
        for candidate in candidates:
            outcome, p_hat, confidence, rationale = self._signal_profile(candidate)
            market_price = candidate["price"] if outcome == "YES" else 1 - candidate["price"]
            ev_pp = round((p_hat - market_price) * 100, 1)
            decision = "watch"
            reason = "edge_below_threshold"
            if ev_pp >= self.min_ev_pp and candidate["slug"] not in seen_market_ids:
                decision = "alert"
                reason = rationale.split(":", 1)[0]
                signals.append(Signal(
                    strategy=self.name,
                    market_id=candidate["slug"],
                    market_title=candidate["title"][:100],
                    outcome=outcome,
                    market_price=round(market_price, 4),
                    p_hat=p_hat,
                    ev_pp=ev_pp,
                    confidence=confidence,
                    closes=candidate["closes"],
                    url=candidate["url"],
                    rationale=rationale,
                ))
                seen_market_ids.add(candidate["slug"])
            self.last_check_details.append({
                "market_slug": candidate["slug"],
                "title": candidate["title"][:120],
                "signal_type": rationale.split(":", 1)[0],
                "current_price": round(candidate["price"], 4),
                "hours_to_close": round(candidate["hours_to_close"], 1),
                "volume": round(candidate["volume"], 2),
                "liquidity": round(candidate["liquidity"], 2),
                "ev_pp": ev_pp,
                "decision": decision,
                "reason": reason,
            })
            if len(signals) >= MAX_ALERTS_PER_RUN:
                break

        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

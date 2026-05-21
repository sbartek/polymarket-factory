"""
Strategy: esport48_v2
Hypothesis: Glicko-2 ratings built from HLTV match history provide better
            win probability estimates than Polymarket for CS2 esport matches.
Method: Compare our Glicko-2 expected win probability against Polymarket price.
        Signal when divergence exceeds threshold and rating confidence (RD) is adequate.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from ..esport_ratings import get_win_probability, MAX_TRADEABLE_RD, MIN_MATCHES
from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

MAX_HOURS_TO_CLOSE = 48.0
MIN_VOLUME = 5_000
MIN_PRICE = 0.08
MAX_PRICE = 0.92
MIN_EDGE_PP = 7.0
MAX_ALERTS_PER_RUN = 5

CS2_TERMS = {
    "cs2", "counter strike", "counter-strike",
    "iem", "esl", "blast", "pgl", "cct",
}

# Exclude non-CS2 esport titles
NON_CS2_PREFIXES = {"lol:", "valorant:", "dota", "league of legends", "overwatch"}


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


def _event_text(ev: dict) -> str:
    parts = []
    for key in ("title", "slug", "ticker", "category"):
        v = ev.get(key)
        if isinstance(v, str):
            parts.append(v.lower())
    tags = ev.get("tags")
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict):
                parts.append((t.get("label") or t.get("slug") or "").lower())
            elif isinstance(t, str):
                parts.append(t.lower())
    return " | ".join(parts)


def _is_cs2_event(ev: dict) -> bool:
    text = _event_text(ev)
    title_lower = (ev.get("title") or "").lower()
    # Exclude non-CS2 esport titles
    if any(title_lower.startswith(p) for p in NON_CS2_PREFIXES):
        return False
    return any(term in text for term in CS2_TERMS)


def _extract_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from 'Counter-Strike: Team A vs Team B (BO3) - Event'."""
    cleaned = title
    # Strip game prefix
    cleaned = re.sub(r"^(Counter-Strike|CS2|CS:GO)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    # Strip BO and event suffix
    cleaned = re.sub(r"\s*\(BO\d\).*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s*-\s*(VCT|PGL|LEC|LCK|LPL|ESL|BLAST|IEM|CCT|DreamLeague|VCL|NODWIN).*",
        "", cleaned, flags=re.IGNORECASE,
    )
    parts = re.split(r"\s+vs\.?\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        a, b = parts[0].strip(), parts[1].strip()
        if a and b:
            return a, b
    return None


class Esport48V2Strategy(Strategy):
    name = "esport48_v2"
    edge_type = "model_vs_market"
    time_window = "intraday"
    target_hold_min_days = 0.04
    target_hold_max_days = 2.0
    scan_frequency = "3x/day"
    max_position_usdc = 5.0
    min_ev_pp = MIN_EDGE_PP
    alert_only = False
    trading_enabled = True  # promoted to paper 2026-05-21: 139 signals over 19 days
    promotable = True
    promotion_criteria = "20 signals with >55% directional accuracy"
    signal_cooldown_hours = 12.0

    def scan(self, markets: list[dict], db=None) -> list[Signal]:
        if db is None:
            from ..db import FactoryDB
            db = FactoryDB()

        candidates = []
        for ev in markets:
            if not _is_cs2_event(ev):
                continue
            price = get_yes_price(ev)
            if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                continue
            hours = _hours_to_close(ev.get("endDate"))
            if hours is None or hours <= 0 or hours > MAX_HOURS_TO_CLOSE:
                continue
            volume = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if volume < MIN_VOLUME:
                continue
            teams = _extract_team_names(ev.get("title") or "")
            if not teams:
                continue
            candidates.append({"ev": ev, "price": price, "hours": hours, "teams": teams})

        print(f"  [{self.name}] {len(candidates)} CS2 candidates within {MAX_HOURS_TO_CLOSE:.0f}h")
        if not candidates:
            return []

        signals: list[Signal] = []
        seen: set[str] = set()

        for cand in candidates:
            ev = cand["ev"]
            team_a, team_b = cand["teams"]
            poly_price = cand["price"]
            slug = str(ev.get("slug", "") or ev.get("id", ""))
            if slug in seen:
                continue

            result = get_win_probability(db, team_a, team_b, game="cs2")
            if not result:
                continue

            # Skip if RD is too high or not enough matches
            if result["team1_rd"] > MAX_TRADEABLE_RD or result["team2_rd"] > MAX_TRADEABLE_RD:
                continue
            if result["team1_matches"] < MIN_MATCHES or result["team2_matches"] < MIN_MATCHES:
                continue

            glicko_prob = result["p1_win"]  # probability team_a (YES) wins
            divergence = glicko_prob - poly_price
            abs_div = abs(divergence)

            if abs_div * 100 < MIN_EDGE_PP:
                continue

            if divergence > 0:
                outcome = "YES"
                market_price = round(poly_price, 4)
                p_hat = round(glicko_prob, 4)
            else:
                outcome = "NO"
                market_price = round(1 - poly_price, 4)
                p_hat = round(1 - glicko_prob, 4)

            ev_pp = round(abs_div * 100, 1)
            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=(ev.get("title") or "?")[:100],
                outcome=outcome,
                market_price=market_price,
                p_hat=p_hat,
                ev_pp=ev_pp,
                confidence=result["confidence"],
                closes=(ev.get("endDate") or "")[:10],
                url=event_url(ev),
                rationale=(
                    f"glicko:{glicko_prob*100:.0f}% vs poly:{poly_price*100:.0f}% "
                    f"({team_a} {result['team1_rating']:.0f}+/-{result['team1_rd']:.0f} "
                    f"vs {team_b} {result['team2_rating']:.0f}+/-{result['team2_rd']:.0f})"
                )[:180],
            ))
            seen.add(slug)

            if len(signals) >= MAX_ALERTS_PER_RUN:
                break

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

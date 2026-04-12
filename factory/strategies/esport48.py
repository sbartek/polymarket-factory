"""
Strategy: esport48
Hypothesis: Polymarket esport odds can lag sharp bookmakers (Pinnacle) when
            liquidity is thin or repricing is slow after roster/map news.
Method: Compare Pinnacle moneyline odds (via OddsPapi) against Polymarket prices.
        Signal when divergence exceeds threshold — Pinnacle's lines embed more
        information than Polymarket's prediction market can reprice in real time.
Status: ALERT-ONLY — accumulate 20 signals before enabling paper trading.

Future (Option B): layer Glicko-2 per-map ratings from HLTV/vlr.gg on top.
See memory: "Esport48 future plan (Option B)" for details.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime

import requests

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
MAX_HOURS_TO_CLOSE = 48.0
MIN_VOLUME = 5_000
MIN_PRICE = 0.08
MAX_PRICE = 0.92
MIN_EDGE_PP = 5.0
MAX_ALERTS_PER_RUN = 5

ESPORT_TERMS = {
    "esport", "esports", "gaming", "valorant", "cs2", "counter strike", "counter-strike",
    "dota", "dota 2", "league of legends", "lol", "rocket league", "overwatch",
    "call of duty", "cod", "rainbow six", "apex", "fortnite", "starcraft", "pubg",
}

# Sport IDs to query from OddsPapi (discovered via /sports endpoint)
# These get populated on first run via _discover_sport_ids()
_ESPORT_SPORT_IDS: list[int] = []

# Cache Pinnacle odds per scan run
_pinnacle_cache: dict[str, dict] = {}


def _get_api_key() -> str | None:
    return os.environ.get("ODDSPAPI_API_KEY")


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
    })
    return " | ".join(chunks)


def _is_esport_event(ev: dict) -> bool:
    text = _event_text(ev)
    return any(term in text for term in ESPORT_TERMS)


def _extract_team_names(title: str) -> tuple[str, str] | None:
    """Extract two team names from an esport match title like 'Team A vs Team B (BO3)'."""
    # Remove common suffixes
    cleaned = re.sub(r"\s*\(BO\d\).*", "", title, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*-\s*(VCT|PGL|LEC|LCK|LPL|ESL|BLAST|IEM|CCT|DreamLeague|VCL).*", "", cleaned, flags=re.IGNORECASE)

    # Split on " vs " or " vs. "
    parts = re.split(r"\s+vs\.?\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        a = parts[0].strip()
        b = parts[1].strip()
        if a and b:
            return a, b
    return None


def _normalize_team(name: str) -> str:
    """Normalize team name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common prefixes/suffixes
    name = re.sub(r"\besports?\b", "", name).strip()
    name = re.sub(r"\bgaming\b", "", name).strip()
    name = re.sub(r"\bteam\b", "", name).strip()
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _team_match_score(poly_name: str, odds_name: str) -> float:
    """Score how well two team names match (0-1)."""
    pn = _normalize_team(poly_name)
    on = _normalize_team(odds_name)
    if not pn or not on:
        return 0.0
    # Exact match
    if pn == on:
        return 1.0
    # One contains the other
    if pn in on or on in pn:
        return 0.8
    # Token overlap
    pt = set(pn.split())
    ot = set(on.split())
    if not pt or not ot:
        return 0.0
    overlap = len(pt & ot)
    return overlap / max(len(pt), len(ot))


def _discover_sport_ids(api_key: str) -> list[int]:
    """Fetch sport IDs for esports titles from OddsPapi."""
    global _ESPORT_SPORT_IDS
    if _ESPORT_SPORT_IDS:
        return _ESPORT_SPORT_IDS
    try:
        resp = requests.get(f"{ODDSPAPI_BASE}/sports", params={"apiKey": api_key}, timeout=10)
        resp.raise_for_status()
        sports = resp.json().get("data", [])
        esport_ids = []
        for s in sports:
            name = (s.get("sportName") or "").lower()
            slug = (s.get("sportSlug") or "").lower()
            if any(term in name or term in slug for term in ["esport", "cs2", "counter-strike",
                    "valorant", "dota", "league of legends", "lol"]):
                esport_ids.append(int(s["sportId"]))
        _ESPORT_SPORT_IDS = esport_ids
        return esport_ids
    except Exception as e:
        print(f"  [esport48] failed to discover sport IDs: {e}")
        return []


def _fetch_pinnacle_odds(api_key: str, sport_ids: list[int]) -> dict[str, dict]:
    """Fetch Pinnacle odds for all esport fixtures. Returns {normalized_key: odds_info}."""
    global _pinnacle_cache
    if _pinnacle_cache:
        return _pinnacle_cache

    odds_by_key: dict[str, dict] = {}
    for sport_id in sport_ids:
        try:
            resp = requests.get(
                f"{ODDSPAPI_BASE}/odds-by-tournaments",
                params={
                    "sportId": sport_id,
                    "bookmaker": "pinnacle",
                    "apiKey": api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            for tournament in data:
                for fixture in tournament.get("fixtures", []):
                    p1 = fixture.get("participant1", {})
                    p2 = fixture.get("participant2", {})
                    p1_name = p1.get("participantName", "")
                    p2_name = p2.get("participantName", "")
                    start_time = fixture.get("startTime", "")

                    # Extract moneyline odds (market 101 = moneyline)
                    bookmakers = fixture.get("bookmakers", {})
                    pinnacle = bookmakers.get("pinnacle", {})
                    markets = pinnacle.get("markets", {})
                    moneyline = markets.get("101", {})  # 101 = moneyline
                    if not moneyline:
                        # Try other common market IDs
                        for mid in ["1", "101", "match_winner"]:
                            if mid in markets:
                                moneyline = markets[mid]
                                break
                    if not moneyline:
                        continue

                    outcomes = moneyline.get("outcomes", {})
                    players = moneyline.get("players", {})

                    # Extract odds for each side
                    home_odds = None
                    away_odds = None
                    for player_id, player_data in players.items():
                        price = player_data.get("price")
                        if price and price > 1.0:
                            # Determine if home or away
                            if str(player_id) == str(p1.get("participantId", "")):
                                home_odds = float(price)
                            elif str(player_id) == str(p2.get("participantId", "")):
                                away_odds = float(price)
                            elif not home_odds:
                                home_odds = float(price)
                            elif not away_odds:
                                away_odds = float(price)

                    if home_odds and away_odds:
                        # Convert decimal odds to implied probability (with overround removal)
                        raw_p1 = 1.0 / home_odds
                        raw_p2 = 1.0 / away_odds
                        overround = raw_p1 + raw_p2
                        if overround > 0:
                            p1_prob = raw_p1 / overround
                            p2_prob = raw_p2 / overround
                        else:
                            continue

                        key = f"{_normalize_team(p1_name)}|{_normalize_team(p2_name)}"
                        odds_by_key[key] = {
                            "p1_name": p1_name,
                            "p2_name": p2_name,
                            "p1_prob": round(p1_prob, 4),
                            "p2_prob": round(p2_prob, 4),
                            "home_odds": home_odds,
                            "away_odds": away_odds,
                            "start_time": start_time,
                            "fixture_id": fixture.get("fixtureId", ""),
                        }
        except Exception as e:
            print(f"  [esport48] odds fetch failed for sport {sport_id}: {e}")

    _pinnacle_cache = odds_by_key
    return odds_by_key


def _find_pinnacle_match(team_a: str, team_b: str, pinnacle_odds: dict[str, dict]) -> dict | None:
    """Find the best matching Pinnacle fixture for a Polymarket match."""
    best_match = None
    best_score = 0.0

    for key, odds in pinnacle_odds.items():
        # Try both orderings
        score_ab = min(
            _team_match_score(team_a, odds["p1_name"]),
            _team_match_score(team_b, odds["p2_name"]),
        )
        score_ba = min(
            _team_match_score(team_a, odds["p2_name"]),
            _team_match_score(team_b, odds["p1_name"]),
        )

        if score_ab >= score_ba:
            score = score_ab
            swapped = False
        else:
            score = score_ba
            swapped = True

        if score > best_score and score >= 0.5:
            best_score = score
            best_match = {**odds, "swapped": swapped, "match_score": score}

    return best_match


class Esport48Strategy(Strategy):
    name = "esport48"
    edge_type = "odds_comparison"
    time_window = "intraday"
    target_hold_min_days = 0.04
    target_hold_max_days = 2.0
    scan_frequency = "3x/day"
    max_position_usdc = 8.0
    min_ev_pp = MIN_EDGE_PP
    alert_only = True
    trading_enabled = False
    promotable = True
    promotion_criteria = "20 signals with >55% directional accuracy"
    signal_cooldown_hours = 24.0
    last_check_details: list[dict] = []

    def scan(self, markets: list[dict]) -> list[Signal]:
        global _pinnacle_cache
        _pinnacle_cache = {}  # Reset per scan
        self.last_check_details = []

        api_key = _get_api_key()
        if not api_key:
            print(f"  [{self.name}] ODDSPAPI_API_KEY not set, 0 alerts")
            return []

        # Filter to esport markets within 48h
        esport_markets = []
        for ev in markets:
            if not _is_esport_event(ev):
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
            esport_markets.append({
                "ev": ev,
                "price": price,
                "hours": hours,
                "volume": volume,
                "teams": teams,
            })

        print(f"  [{self.name}] {len(esport_markets)} esport candidates within {MAX_HOURS_TO_CLOSE:.0f}h")
        if not esport_markets:
            print(f"  [{self.name}] 0 alerts")
            return []

        # Fetch Pinnacle odds (1 API call per sport ID)
        sport_ids = _discover_sport_ids(api_key)
        if not sport_ids:
            # Fallback: try common esport sport IDs
            sport_ids = [17, 18, 19, 20, 21, 22]
        pinnacle_odds = _fetch_pinnacle_odds(api_key, sport_ids)
        print(f"  [{self.name}] {len(pinnacle_odds)} Pinnacle fixtures loaded")

        signals: list[Signal] = []
        seen: set[str] = set()

        for candidate in esport_markets:
            ev = candidate["ev"]
            team_a, team_b = candidate["teams"]
            poly_price = candidate["price"]
            slug = str(ev.get("slug", "") or ev.get("id", ""))
            if slug in seen:
                continue

            match = _find_pinnacle_match(team_a, team_b, pinnacle_odds)
            if not match:
                self.last_check_details.append({
                    "market_slug": slug,
                    "title": (ev.get("title") or "")[:80],
                    "poly_price": round(poly_price, 4),
                    "decision": "skip",
                    "reason": "no_pinnacle_match",
                })
                continue

            # Determine which Pinnacle probability corresponds to Polymarket YES
            # Polymarket YES = team_a wins (first team in "A vs B" title)
            if match["swapped"]:
                pinnacle_yes_prob = match["p2_prob"]
            else:
                pinnacle_yes_prob = match["p1_prob"]

            divergence = pinnacle_yes_prob - poly_price
            abs_div = abs(divergence)

            self.last_check_details.append({
                "market_slug": slug,
                "title": (ev.get("title") or "")[:80],
                "poly_price": round(poly_price, 4),
                "pinnacle_prob": round(pinnacle_yes_prob, 4),
                "divergence_pp": round(divergence * 100, 1),
                "match_score": round(match["match_score"], 2),
                "pinnacle_teams": f"{match['p1_name']} vs {match['p2_name']}",
                "decision": "alert" if abs_div * 100 >= MIN_EDGE_PP else "watch",
                "reason": "pinnacle_divergence" if abs_div * 100 >= MIN_EDGE_PP else "edge_below_threshold",
            })

            if abs_div * 100 < MIN_EDGE_PP:
                continue

            if divergence > 0:
                outcome = "YES"
                market_price = round(poly_price, 4)
                p_hat = round(pinnacle_yes_prob, 4)
            else:
                outcome = "NO"
                market_price = round(1 - poly_price, 4)
                p_hat = round(1 - pinnacle_yes_prob, 4)

            ev_pp = round(abs_div * 100, 1)
            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=(ev.get("title") or "?")[:100],
                outcome=outcome,
                market_price=market_price,
                p_hat=p_hat,
                ev_pp=ev_pp,
                confidence="high" if ev_pp >= 10 else "medium",
                closes=(ev.get("endDate") or "")[:10],
                url=event_url(ev),
                rationale=(
                    f"pinnacle:{pinnacle_yes_prob*100:.0f}% vs poly:{poly_price*100:.0f}% "
                    f"({match['p1_name']} vs {match['p2_name']}, "
                    f"match:{match['match_score']:.0%})"
                )[:180],
            ))
            seen.add(slug)

            if len(signals) >= MAX_ALERTS_PER_RUN:
                break

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

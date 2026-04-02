"""
Strategy: weather_edge
Hypothesis: Polymarket daily temperature markets (e.g. "Will the highest temp in NYC be
            between 62-63°F on April 2?") are priced from crowd intuition. Open-Meteo
            ensemble (50 ECMWF members) provides calibrated probabilities.
Method: No LLM. Regex-parses sub-market questions → geocode → ensemble probability.
        Works at the binary sub-market level within multi-outcome temperature events.
        Caches geocoding and ensemble calls per (city, date, metric).
Frequency: 3x/day. Most useful for markets 1–7 days out.
"""
import json
import re
from datetime import date, datetime

import requests

from ..feed import event_url, fetch_by_tag
from ..models import Signal
from .base import Strategy

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

WEATHER_KEYWORDS = [
    "highest temperature", "lowest temperature", "high temperature",
    "temperature", "highest temp", "lowest temp",
]

MAX_DAYS_TO_CLOSE = 10
MIN_DAYS_TO_CLOSE = 0


def _is_weather_event(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in WEATHER_KEYWORDS)


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        close = date.fromisoformat(end_date[:10])
        return (close - date.today()).days
    except ValueError:
        return None


def _geocode(location: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            GEOCODING_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=8,
        )
        data = resp.json()
        results = data.get("results") or []
        if results:
            return float(results[0]["latitude"]), float(results[0]["longitude"])
    except Exception:
        pass
    return None


def _get_ensemble_values(lat: float, lon: float, target_date: str, metric: str, unit: str) -> list[float] | None:
    """
    Fetch hourly ensemble temperature for target_date, then compute daily max or min
    across all members. Returns list of per-member daily values.
    """
    if metric not in ("temperature_max", "temperature_min"):
        return None

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "start_date": target_date,
        "end_date": target_date,
        "timezone": "auto",
        "temperature_unit": "fahrenheit" if unit == "F" else "celsius",
    }
    try:
        resp = requests.get(ENSEMBLE_URL, params=params, timeout=15)
        data = resp.json()
        hourly = data.get("hourly", {})

        # Collect all member columns (temperature_2m_member01, ...)
        member_keys = [k for k in hourly if k.startswith("temperature_2m_member")]
        if not member_keys:
            return None

        reducer = max if metric == "temperature_max" else min
        values = []
        for key in member_keys:
            member_vals = [v for v in hourly[key] if v is not None]
            if member_vals:
                values.append(float(reducer(member_vals)))
        return values if values else None
    except Exception:
        return None


def _parse_submarket_question(question: str) -> dict | None:
    """
    Parse structured temperature market questions:
      "Will the highest temperature in Atlanta be between 60-61°F on March 28?"
      "Will the highest temperature in Atlanta be 55°F or below on March 28?"
      "Will the highest temperature in Shanghai be 16°C on March 28?"
    Returns dict with keys: location, target_date, metric, unit, direction,
      and either (threshold) for above/below or (threshold_low, threshold_high) for range.
    """
    q = question
    ql = q.lower()

    if "highest temperature" in ql:
        metric = "temperature_max"
    elif "lowest temperature" in ql:
        metric = "temperature_min"
    else:
        return None

    # Unit: look for °F or °C explicitly
    if re.search(r"°[Ff]", q):
        unit = "F"
    elif re.search(r"°[Cc]", q):
        unit = "C"
    else:
        return None

    # Location: "in {CITY} be"
    loc_match = re.search(r"\bin (.+?) be\b", q, re.IGNORECASE)
    if not loc_match:
        return None
    location = loc_match.group(1).strip()

    # Date: "on {Month} {Day}"
    date_match = re.search(r"\bon (\w+ \d+)\b", q, re.IGNORECASE)
    if not date_match:
        return None
    try:
        target_date = datetime.strptime(
            f"{date_match.group(1)} {date.today().year}", "%B %d %Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        return None

    base = {"location": location, "target_date": target_date, "metric": metric, "unit": unit}

    # Range: "between 60-61°" or just "60-61°"
    range_match = re.search(r"(?:between )?(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)°", q, re.IGNORECASE)
    if range_match:
        return {**base, "direction": "range",
                "threshold_low": float(range_match.group(1)),
                "threshold_high": float(range_match.group(2))}

    # Single value + modifier
    single_match = re.search(r"be (\d+(?:\.\d+)?)°", q, re.IGNORECASE)
    if single_match:
        val = float(single_match.group(1))
        if "or below" in ql:
            return {**base, "direction": "below", "threshold": val}
        if "or above" in ql:
            return {**base, "direction": "above", "threshold": val}
        # Exact single degree — treat as [val, val+1)
        return {**base, "direction": "range", "threshold_low": val, "threshold_high": val + 1}

    return None


def _prob_from_values(values: list[float], parsed: dict) -> float | None:
    n = len(values)
    if not n:
        return None
    direction = parsed["direction"]
    if direction == "above":
        satisfied = sum(1 for v in values if v >= parsed["threshold"])
    elif direction == "below":
        satisfied = sum(1 for v in values if v <= parsed["threshold"])
    elif direction == "range":
        lo, hi = parsed["threshold_low"], parsed["threshold_high"]
        satisfied = sum(1 for v in values if lo <= v <= hi)
    else:
        return None
    return round(satisfied / n, 4)


class WeatherEdgeStrategy(Strategy):
    name = "weather_edge"
    paused = True
    max_position_usdc = 12.0
    min_ev_pp = 12.0
    min_position_usdc = 2.0

    def __init__(self):
        self._geo_cache: dict = {}
        self._ensemble_cache: dict = {}

    def _get_coords(self, location: str) -> tuple[float, float] | None:
        if location not in self._geo_cache:
            self._geo_cache[location] = _geocode(location)
        return self._geo_cache[location]

    def _get_values(self, location: str, target_date: str, metric: str, unit: str) -> list[float] | None:
        key = f"{location}:{target_date}:{metric}:{unit}"
        if key not in self._ensemble_cache:
            coords = self._get_coords(location)
            if coords is None:
                self._ensemble_cache[key] = None
            else:
                self._ensemble_cache[key] = _get_ensemble_values(
                    coords[0], coords[1], target_date, metric, unit
                )
        return self._ensemble_cache[key]

    def scan(self, markets: list[dict]) -> list[Signal]:
        # Fetch weather-tagged events + any weather events in top markets
        weather_tag_events = []
        try:
            weather_tag_events = fetch_by_tag("weather", limit=30)
        except Exception:
            pass

        seen: set[str] = set()
        all_events = []
        for ev in markets + weather_tag_events:
            slug = ev.get("slug") or str(ev.get("id", ""))
            if slug not in seen:
                seen.add(slug)
                all_events.append(ev)

        # Keep only weather events within our horizon
        weather_events = [
            ev for ev in all_events
            if _is_weather_event(ev.get("title") or "")
            and (d := _days_to_close(ev.get("endDate"))) is not None
            and MIN_DAYS_TO_CLOSE <= d <= MAX_DAYS_TO_CLOSE
        ]
        print(f"  [{self.name}] {len(weather_events)} weather events (≤{MAX_DAYS_TO_CLOSE}d)")

        signals: list[Signal] = []

        for ev in weather_events:
            slug = ev.get("slug", "") or str(ev.get("id", ""))
            url = event_url(ev)
            closes = (ev.get("endDate") or "")[:10]

            for m in ev.get("markets", []):
                if m.get("closed"):
                    continue

                # Get YES price for this sub-market
                prices_raw = m.get("outcomePrices", "[]")
                try:
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    yes_price = float(prices[0])
                except (ValueError, TypeError, IndexError):
                    continue

                # Skip near-certain (already resolved or never interesting)
                if yes_price < 0.02 or yes_price > 0.98:
                    continue

                question = m.get("question") or ""
                parsed = _parse_submarket_question(question)
                if parsed is None:
                    continue

                values = self._get_values(
                    parsed["location"], parsed["target_date"],
                    parsed["metric"], parsed["unit"]
                )
                if not values:
                    continue

                prob = _prob_from_values(values, parsed)
                if prob is None:
                    continue

                ev_pp = (prob - yes_price) * 100
                if abs(ev_pp) < self.min_ev_pp:
                    continue

                outcome = "YES" if ev_pp > 0 else "NO"
                mp = yes_price if outcome == "YES" else round(1 - yes_price, 4)
                ph = prob if outcome == "YES" else round(1 - prob, 4)

                direction_str = parsed["direction"]
                if direction_str == "range":
                    tstr = f"{parsed['threshold_low']}-{parsed['threshold_high']}{parsed['unit']}"
                else:
                    tstr = f"{'>' if direction_str == 'above' else '<'}{parsed['threshold']}{parsed['unit']}"

                signals.append(Signal(
                    strategy=self.name,
                    market_id=f"{slug}:{m.get('id', '')}",
                    market_title=question[:100],
                    outcome=outcome,
                    market_price=mp,
                    p_hat=ph,
                    ev_pp=round(abs(ev_pp), 1),
                    confidence="medium",
                    closes=closes,
                    url=url,
                    rationale=(
                        f"ensemble:{prob*100:.0f}% vs market:{yes_price*100:.0f}% "
                        f"({parsed['location']},{tstr})"
                    ),
                ))

        print(f"  [{self.name}] {len(signals)} signals")
        return signals

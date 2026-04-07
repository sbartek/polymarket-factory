"""
Strategy: weather_convergence
Hypothesis: As forecast date approaches, ECMWF ensemble spread narrows dramatically.
Markets opened 3-5 days out may still reflect the old uncertain forecast. When the
latest ensemble strongly favors a bin that the market underprices, bet YES on it.

Only signals on events 0-2 days out where the ensemble has converged (low spread).
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

WEATHER_KEYWORDS = ["highest temperature", "lowest temperature"]
MAX_DAYS_TO_CLOSE = 2      # only signal when forecast is most accurate
MIN_ENSEMBLE_PROB = 0.40    # ensemble must give ≥40% to the bin
MAX_MARKET_PRICE = 0.30     # market must underprice relative to ensemble
MIN_EV_PP = 12.0
MAX_ALERTS_PER_RUN = 4


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _geocode(location: str) -> tuple[float, float] | None:
    try:
        resp = requests.get(
            GEOCODING_URL,
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=8,
        )
        results = resp.json().get("results") or []
        if results:
            return float(results[0]["latitude"]), float(results[0]["longitude"])
    except Exception:
        pass
    return None


def _get_ensemble_max_temps(lat: float, lon: float, target_date: str, unit: str) -> list[float] | None:
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m",
        "start_date": target_date, "end_date": target_date,
        "timezone": "auto",
        "temperature_unit": "fahrenheit" if unit == "F" else "celsius",
    }
    try:
        resp = requests.get(ENSEMBLE_URL, params=params, timeout=15)
        hourly = resp.json().get("hourly", {})
        member_keys = [k for k in hourly if k.startswith("temperature_2m_member")]
        if not member_keys:
            return None
        values = []
        for key in member_keys:
            member_vals = [v for v in hourly[key] if v is not None]
            if member_vals:
                values.append(float(max(member_vals)))
        return values if values else None
    except Exception:
        return None


def _parse_bin(question: str) -> dict | None:
    q = question
    ql = q.lower()
    if "highest temperature" not in ql and "highest temp" not in ql:
        return None
    unit = "F" if re.search(r"°[Ff]", q) else ("C" if re.search(r"°[Cc]", q) else None)
    if not unit:
        return None
    loc_match = re.search(r"\bin (.+?) be\b", q, re.IGNORECASE)
    if not loc_match:
        return None
    date_match = re.search(r"\bon (\w+ \d+)\b", q, re.IGNORECASE)
    if not date_match:
        return None
    try:
        target_date = datetime.strptime(
            f"{date_match.group(1)} {date.today().year}", "%B %d %Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        return None

    location = loc_match.group(1).strip()

    range_match = re.search(r"(?:between )?(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)°", q)
    if range_match:
        return {"location": location, "target_date": target_date, "unit": unit,
                "lo": float(range_match.group(1)), "hi": float(range_match.group(2))}

    single_match = re.search(r"be (\d+(?:\.\d+)?)°", q)
    if single_match:
        val = float(single_match.group(1))
        if "or below" in ql:
            return {"location": location, "target_date": target_date, "unit": unit,
                    "lo": -999, "hi": val + 0.5}
        if "or above" in ql:
            return {"location": location, "target_date": target_date, "unit": unit,
                    "lo": val - 0.5, "hi": 999}
        return {"location": location, "target_date": target_date, "unit": unit,
                "lo": val, "hi": val + 1}
    return None


class WeatherConvergenceStrategy(Strategy):
    name = "weather_convergence"
    edge_type = "information"
    time_window = "super_short"
    target_hold_min_days = 0.02
    target_hold_max_days = 2
    scan_frequency = "3x/day"
    max_position_usdc = 5.0
    min_ev_pp = 12.0
    alert_only = True
    trading_enabled = False

    def __init__(self):
        self._geo_cache: dict = {}
        self._ensemble_cache: dict = {}

    def scan(self, markets: list[dict]) -> list[Signal]:
        weather_events = []
        try:
            weather_events = fetch_by_tag("weather", limit=50)
        except Exception:
            pass

        seen: set[str] = set()
        all_events = []
        for ev in markets + weather_events:
            slug = ev.get("slug") or str(ev.get("id", ""))
            if slug not in seen:
                seen.add(slug)
                all_events.append(ev)

        signals: list[Signal] = []

        for ev in all_events:
            title = (ev.get("title") or "").lower()
            if not any(kw in title for kw in WEATHER_KEYWORDS):
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or days < 1 or days > MAX_DAYS_TO_CLOSE:
                continue

            slug = ev.get("slug", "") or str(ev.get("id", ""))
            url = event_url(ev)
            closes = (ev.get("endDate") or "")[:10]

            # Parse all bins and group by location/date
            bins_by_key: dict[str, list] = {}
            for m in ev.get("markets", []):
                if m.get("closed"):
                    continue
                question = m.get("question") or ""
                parsed = _parse_bin(question)
                if not parsed:
                    continue
                prices_raw = m.get("outcomePrices", "[]")
                try:
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    yes_price = float(prices[0])
                except (ValueError, TypeError, IndexError):
                    continue
                key = f"{parsed['location']}:{parsed['target_date']}:{parsed['unit']}"
                bins_by_key.setdefault(key, []).append({
                    "id": str(m.get("id", "")),
                    "question": question[:100],
                    "yes_price": yes_price,
                    "lo": parsed["lo"],
                    "hi": parsed["hi"],
                    "parsed": parsed,
                })

            for key, bins in bins_by_key.items():
                location, target_date, unit = key.split(":")

                if location not in self._geo_cache:
                    self._geo_cache[location] = _geocode(location)
                coords = self._geo_cache[location]
                if not coords:
                    continue

                cache_key = f"{location}:{target_date}:{unit}"
                if cache_key not in self._ensemble_cache:
                    self._ensemble_cache[cache_key] = _get_ensemble_max_temps(
                        coords[0], coords[1], target_date, unit
                    )
                values = self._ensemble_cache[cache_key]
                if not values:
                    continue

                n = len(values)
                # Check ensemble spread — only signal if converged
                spread = max(values) - min(values)
                if spread > 6:  # too uncertain still
                    continue

                for b in bins:
                    # Count ensemble members in this bin
                    count = sum(1 for v in values if b["lo"] <= v < b["hi"])
                    ensemble_prob = count / n

                    if ensemble_prob < MIN_ENSEMBLE_PROB:
                        continue
                    if b["yes_price"] > MAX_MARKET_PRICE:
                        continue

                    ev_pp = round((ensemble_prob - b["yes_price"]) * 100, 1)
                    if ev_pp < MIN_EV_PP:
                        continue

                    signals.append(Signal(
                        strategy=self.name,
                        market_id=f"{slug}:{b['id']}",
                        market_title=b["question"],
                        outcome="YES",
                        market_price=round(b["yes_price"], 4),
                        p_hat=round(ensemble_prob, 4),
                        ev_pp=ev_pp,
                        confidence="high" if ev_pp >= 20 else "medium",
                        closes=closes,
                        url=url,
                        rationale=f"convergence:{location},ensemble={ensemble_prob*100:.0f}%,market={b['yes_price']*100:.0f}%,spread={spread:.1f}",
                    ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

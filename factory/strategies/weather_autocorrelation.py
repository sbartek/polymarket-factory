"""
Strategy: weather_autocorrelation
Hypothesis: Temperature anomalies persist for 1-2 days. If today's actual high was
significantly above/below the ensemble forecast, tomorrow's bins may not yet reflect
this surprise. Bet in the direction of today's deviation.

Uses Open-Meteo historical API for today's actual temp and ensemble for tomorrow's forecast.
"""
import json
import re
from datetime import date, datetime, timedelta

import requests

from ..feed import event_url, fetch_by_tag
from ..models import Signal
from .base import Strategy

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
HISTORICAL_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_KEYWORDS = ["highest temperature", "lowest temperature"]
MIN_SURPRISE_DEG = 2.0     # today must have deviated ≥2° from ensemble median
MAX_DAYS_TO_CLOSE = 2
MIN_EV_PP = 10.0
MAX_ALERTS_PER_RUN = 4
AUTOCORR_FACTOR = 0.3      # 30% of yesterday's surprise expected to persist tomorrow
MAX_P_HAT = 0.70           # cap ensemble-derived probability to prevent overconfidence


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


def _get_actual_max_temp(lat: float, lon: float, target_date: str, unit: str) -> float | None:
    """Get actual observed max temperature for a date."""
    params = {
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_max",
        "start_date": target_date, "end_date": target_date,
        "timezone": "auto",
        "temperature_unit": "fahrenheit" if unit == "F" else "celsius",
    }
    try:
        resp = requests.get(HISTORICAL_URL, params=params, timeout=10)
        daily = resp.json().get("daily", {})
        temps = daily.get("temperature_2m_max", [])
        return float(temps[0]) if temps else None
    except Exception:
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
                "lo": float(range_match.group(1)), "hi": float(range_match.group(2)),
                "mid": (float(range_match.group(1)) + float(range_match.group(2))) / 2}

    single_match = re.search(r"be (\d+(?:\.\d+)?)°", q)
    if single_match:
        val = float(single_match.group(1))
        if "or below" in ql or "or above" in ql or "or lower" in ql or "or higher" in ql:
            return None  # skip boundary bins — too complex
        return {"location": location, "target_date": target_date, "unit": unit,
                "lo": val, "hi": val + 1, "mid": val + 0.5}
    return None


class WeatherAutocorrelationStrategy(Strategy):
    name = "weather_autocorrelation"
    edge_type = "statistical_fade"
    time_window = "super_short"
    target_hold_min_days = 0.02
    target_hold_max_days = 2
    scan_frequency = "3x/day"
    max_position_usdc = 5.0
    min_ev_pp = 10.0
    alert_only = True
    trading_enabled = False

    def __init__(self):
        self._geo_cache: dict = {}

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

        # Group future bins by location
        location_bins: dict[str, list] = {}
        event_meta: dict[str, dict] = {}

        for ev in all_events:
            title = (ev.get("title") or "").lower()
            if not any(kw in title for kw in WEATHER_KEYWORDS):
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or days < 1 or days > MAX_DAYS_TO_CLOSE:
                continue

            slug = ev.get("slug", "") or str(ev.get("id", ""))
            event_meta[slug] = {"url": event_url(ev), "closes": (ev.get("endDate") or "")[:10]}

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

                key = f"{parsed['location']}:{parsed['unit']}"
                location_bins.setdefault(key, []).append({
                    "slug": slug,
                    "id": str(m.get("id", "")),
                    "question": question[:100],
                    "yes_price": yes_price,
                    "parsed": parsed,
                })

        signals: list[Signal] = []
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        for key, bins in location_bins.items():
            location, unit = key.split(":")

            if location not in self._geo_cache:
                self._geo_cache[location] = _geocode(location)
            coords = self._geo_cache[location]
            if not coords:
                continue

            # Get yesterday's actual temperature
            actual = _get_actual_max_temp(coords[0], coords[1], yesterday, unit)
            if actual is None:
                continue

            # Get yesterday's ensemble forecast (what was expected)
            ensemble_yesterday = _get_ensemble_max_temps(
                coords[0], coords[1], yesterday, unit
            )
            if not ensemble_yesterday:
                continue

            median_forecast = sorted(ensemble_yesterday)[len(ensemble_yesterday) // 2]
            surprise = actual - median_forecast

            if abs(surprise) < MIN_SURPRISE_DEG:
                continue

            # Group bins by target_date — each date needs its own ensemble fetch
            bins_by_date: dict[str, list] = {}
            for b in bins:
                bins_by_date.setdefault(b["parsed"]["target_date"], []).append(b)

            for target_date, date_bins in bins_by_date.items():
                # Fetch ensemble for the target date and shift by autocorrelation factor
                ensemble_target = _get_ensemble_max_temps(
                    coords[0], coords[1], target_date, unit
                )
                if not ensemble_target:
                    continue

                shifted = [v + surprise * AUTOCORR_FACTOR for v in ensemble_target]
                n = len(shifted)

                for b in date_bins:
                    bin_mid = b["parsed"]["mid"]
                    # Only signal bins in the surprise direction
                    if surprise > 0 and bin_mid <= median_forecast:
                        continue
                    if surprise < 0 and bin_mid >= median_forecast:
                        continue

                    lo, hi = b["parsed"]["lo"], b["parsed"]["hi"]
                    count = sum(1 for v in shifted if lo <= v < hi)
                    adj_prob = round(min(count / n, MAX_P_HAT), 4)

                    ev_pp = round((adj_prob - b["yes_price"]) * 100, 1)
                    if ev_pp < MIN_EV_PP:
                        continue

                    meta = event_meta.get(b["slug"], {})
                    signals.append(Signal(
                        strategy=self.name,
                        market_id=f"{b['slug']}:{b['id']}",
                        market_title=b["question"],
                        outcome="YES",
                        market_price=round(b["yes_price"], 4),
                        p_hat=adj_prob,
                        ev_pp=ev_pp,
                        confidence="medium",
                        closes=meta.get("closes", ""),
                        url=meta.get("url", ""),
                        rationale=(
                            f"autocorr:{location},surprise={surprise:+.1f},"
                            f"actual={actual:.1f},forecast={median_forecast:.1f},"
                            f"shifted_prob={adj_prob*100:.0f}%"
                        ),
                    ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(signals)} alerts")
        return signals

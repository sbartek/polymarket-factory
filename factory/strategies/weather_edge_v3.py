"""
Strategy: weather_edge_v3
Hypothesis: Same-day temperature bin markets are exploitable via real-time
observations — no forecasting required. By mid-morning the day's minimum
temperature is established (occurs near sunrise). By late afternoon the day's
maximum is established. Bins already made impossible by what has been observed
can be shorted with near-zero residual risk.

Edge: information-lag arbitrage. Market participants don't update prices based
on real-time temperature data; Open-Meteo gives us the observed hourly record.

Method:
  MIN temp: signal after 10am local when observed_min < bin_low − BUFFER
  MAX temp: signal after 3pm local when observed_max > bin_high + BUFFER
  No LLM. No ensemble forecasting.

Status: ALERT-ONLY — accumulate signals to validate accuracy before paper trading.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta

import requests

from ..feed import event_url, fetch_by_tag
from ..models import Signal
from .base import Strategy

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_KEYWORDS = [
    "highest temperature", "lowest temperature", "high temperature",
    "temperature", "highest temp", "lowest temp",
]

MAX_DAYS_TO_CLOSE = 0       # same-day only — tomorrow's data would be forecasts, not observations
MIN_HOUR_FOR_MIN = 10       # only signal MIN after 10am local (day's low established)
MIN_HOUR_FOR_MAX = 15       # only signal MAX after 3pm local (day's high established)
LATE_HOUR = 18              # after 6pm local: bin that was never reached is also dead
BUFFER_C = 2.0              # °C safety margin for remaining variation
BUFFER_F = 3.6              # equivalent buffer in °F
MIN_MARKET_PRICE = 0.08     # market must still price the bin at >8% for edge to exist
MAX_MARKET_PRICE = 0.92     # skip near-certain YES bins
MAX_ALERTS_PER_RUN = 6
P_HAT_ELIMINATED = 0.97     # p(NO) when bin is observationally eliminated


def _is_weather_event(title: str) -> bool:
    return any(kw in title.lower() for kw in WEATHER_KEYWORDS)


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


def _get_today_hourly(
    lat: float, lon: float, target_date: str, unit: str
) -> tuple[list[float], int] | None:
    """Fetch all 24 hourly temps for target_date at (lat, lon).

    Returns (hourly_temps, utc_offset_seconds).
    hourly_temps[i] is the temperature at local midnight + i hours.
    Past hours are observations; future hours are short-range forecasts.
    """
    try:
        resp = requests.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "start_date": target_date,
                "end_date": target_date,
                "timezone": "auto",
                "temperature_unit": "fahrenheit" if unit == "F" else "celsius",
            },
            timeout=15,
        )
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        utc_offset = data.get("utc_offset_seconds", 0)
        if not temps:
            return None
        return [float(t) for t in temps if t is not None], utc_offset
    except Exception:
        return None


def _local_hour_now(utc_offset_seconds: int) -> int:
    local_dt = datetime.now(UTC) + timedelta(seconds=utc_offset_seconds)
    return local_dt.hour


def _parse_submarket_question(question: str) -> dict | None:
    q = question
    ql = q.lower()

    if "highest temperature" in ql or "highest temp" in ql:
        metric = "temperature_max"
    elif "lowest temperature" in ql or "lowest temp" in ql:
        metric = "temperature_min"
    else:
        return None

    if re.search(r"°[Ff]", q):
        unit = "F"
    elif re.search(r"°[Cc]", q):
        unit = "C"
    else:
        return None

    loc_match = re.search(r"\bin (.+?) be\b", q, re.IGNORECASE)
    if not loc_match:
        return None
    location = loc_match.group(1).strip()

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

    range_match = re.search(r"(?:between )?(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)°", q, re.IGNORECASE)
    if range_match:
        return {**base, "direction": "range",
                "threshold_low": float(range_match.group(1)),
                "threshold_high": float(range_match.group(2))}

    single_match = re.search(r"be (\d+(?:\.\d+)?)°", q, re.IGNORECASE)
    if single_match:
        val = float(single_match.group(1))
        if "or below" in ql or "or lower" in ql:
            return {**base, "direction": "below", "threshold": val}
        if "or above" in ql or "or higher" in ql:
            return {**base, "direction": "above", "threshold": val}
        return {**base, "direction": "range", "threshold_low": val, "threshold_high": val + 1}

    return None


def _bin_eliminated(observed: float, local_hour: int, metric: str, parsed: dict) -> bool:
    """Return True if the bin is observationally impossible.

    Two elimination directions for each metric:

    MIN temp (after MIN_HOUR_FOR_MIN):
      - min already BELOW bin bottom: observed_min < bin_low - buf (can't rise back in)
      - min too HIGH for bin after LATE_HOUR: observed_min > bin_high + buf (night never got cold)

    MAX temp (after MIN_HOUR_FOR_MAX):
      - max already ABOVE bin top: observed_max > bin_high + buf (can't fall back in)
      - max too LOW for bin after LATE_HOUR: observed_max < bin_low - buf (day never got warm)
    """
    unit = parsed["unit"]
    buf = BUFFER_F if unit == "F" else BUFFER_C
    direction = parsed["direction"]

    if metric == "temperature_min":
        if local_hour < MIN_HOUR_FOR_MIN:
            return False
        if direction == "range":
            lo, hi = parsed["threshold_low"], parsed["threshold_high"]
            # Min went below the bin
            if observed < lo - buf:
                return True
            # Min stayed too high (night not cold enough) — needs late hour
            if local_hour >= LATE_HOUR and observed > hi + buf:
                return True
        elif direction == "above":
            # bin wins if min >= threshold
            if observed < parsed["threshold"] - buf:
                return True
            if local_hour >= LATE_HOUR and observed > parsed["threshold"] + buf:
                return True
        # "below X": if min < X it's a YES; if min > X + buf at late hour → this bin dead
        elif direction == "below":
            if local_hour >= LATE_HOUR and observed > parsed["threshold"] + buf:
                return True

    elif metric == "temperature_max":
        if local_hour < MIN_HOUR_FOR_MAX:
            return False
        if direction == "range":
            lo, hi = parsed["threshold_low"], parsed["threshold_high"]
            # Max exceeded the bin
            if observed > hi + buf:
                return True
            # Max never reached the bin (day not warm enough) — needs late hour
            if local_hour >= LATE_HOUR and observed < lo - buf:
                return True
        elif direction == "below":
            # bin wins if max < threshold
            if observed > parsed["threshold"] + buf:
                return True
            if local_hour >= LATE_HOUR and observed < parsed["threshold"] - buf:
                return True
        # "above X": if max >= X it's a YES; if max < X - buf at late hour → this bin dead
        elif direction == "above":
            if local_hour >= LATE_HOUR and observed < parsed["threshold"] - buf:
                return True

    return False


class WeatherEdgeV3Strategy(Strategy):
    name = "weather_edge_v3"
    edge_type = "model_vs_market"
    time_window = "super_short"
    target_hold_min_days = 0.0
    target_hold_max_days = 1.0
    scan_frequency = "3x/day"
    max_position_usdc = 10.0
    min_ev_pp = 15.0
    alert_only = True
    trading_enabled = False
    promotable = True
    promotion_criteria = "20 signals with >80% NO accuracy"
    last_check_details: list[dict] = []

    def __init__(self) -> None:
        self._geo_cache: dict = {}
        self._obs_cache: dict = {}

    def _get_coords(self, location: str) -> tuple[float, float] | None:
        if location not in self._geo_cache:
            self._geo_cache[location] = _geocode(location)
        return self._geo_cache[location]

    def _get_hourly(
        self, location: str, target_date: str, unit: str
    ) -> tuple[list[float], int] | None:
        key = f"{location}:{target_date}:{unit}"
        if key not in self._obs_cache:
            coords = self._get_coords(location)
            self._obs_cache[key] = (
                _get_today_hourly(coords[0], coords[1], target_date, unit)
                if coords else None
            )
        return self._obs_cache[key]

    def scan(self, markets: list[dict]) -> list[Signal]:
        self.last_check_details = []

        weather_tag_events: list[dict] = []
        try:
            weather_tag_events = fetch_by_tag("weather", limit=30)
        except Exception:
            pass

        seen: set[str] = set()
        all_events: list[dict] = []
        for ev in markets + weather_tag_events:
            slug = ev.get("slug") or str(ev.get("id", ""))
            if slug not in seen:
                seen.add(slug)
                all_events.append(ev)

        weather_events = [
            ev for ev in all_events
            if _is_weather_event(ev.get("title") or "")
            and (d := _days_to_close(ev.get("endDate"))) is not None
            and 0 <= d <= MAX_DAYS_TO_CLOSE
        ]
        print(f"  [{self.name}] {len(weather_events)} same-day/next-day weather events")

        signals: list[Signal] = []

        for ev in weather_events:
            slug = ev.get("slug", "") or str(ev.get("id", ""))
            url = event_url(ev)
            closes = (ev.get("endDate") or "")[:10]

            for m in ev.get("markets", []):
                if m.get("closed"):
                    continue

                prices_raw = m.get("outcomePrices", "[]")
                try:
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    yes_price = float(prices[0])
                except (ValueError, TypeError, IndexError):
                    continue

                if not (MIN_MARKET_PRICE <= yes_price <= MAX_MARKET_PRICE):
                    continue

                question = m.get("question") or ""
                parsed = _parse_submarket_question(question)
                if parsed is None:
                    continue

                # Only use observational data for today — future dates would be forecasts
                if parsed["target_date"] != date.today().isoformat():
                    continue

                result = self._get_hourly(parsed["location"], parsed["target_date"], parsed["unit"])
                if result is None:
                    continue
                hourly_temps, utc_offset = result

                local_hour = _local_hour_now(utc_offset)
                past_temps = hourly_temps[:local_hour]
                if not past_temps:
                    continue

                metric = parsed["metric"]
                observed = min(past_temps) if metric == "temperature_min" else max(past_temps)

                if not _bin_eliminated(observed, local_hour, metric, parsed):
                    continue

                no_price = round(1 - yes_price, 4)
                ev_pp = round((no_price - (1 - P_HAT_ELIMINATED)) * 100, 1)
                if ev_pp < self.min_ev_pp:
                    continue

                direction = parsed["direction"]
                if direction == "range":
                    tstr = f"{parsed['threshold_low']}-{parsed['threshold_high']}{parsed['unit']}"
                elif direction == "above":
                    tstr = f">{parsed['threshold']}{parsed['unit']}"
                else:
                    tstr = f"<{parsed['threshold']}{parsed['unit']}"

                obs_label = "min" if metric == "temperature_min" else "max"
                self.last_check_details.append({
                    "market_slug": slug,
                    "title": question[:80],
                    "yes_price": yes_price,
                    "observed": observed,
                    "local_hour": local_hour,
                    "direction": direction,
                    "decision": "alert",
                    "reason": f"NO:obs_{obs_label}={observed:.1f} eliminates {tstr}",
                })

                signals.append(Signal(
                    strategy=self.name,
                    market_id=f"{slug}:{m.get('id', '')}",
                    market_title=question[:100],
                    outcome="NO",
                    market_price=no_price,
                    p_hat=P_HAT_ELIMINATED,
                    ev_pp=ev_pp,
                    confidence="high",
                    closes=closes,
                    url=url,
                    rationale=(
                        f"obs-v3:{obs_label}={observed:.1f}{parsed['unit']} "
                        f"eliminates bin {tstr} at {local_hour:02d}:00 local"
                    ),
                ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(signals)} observational NO alerts")
        return signals

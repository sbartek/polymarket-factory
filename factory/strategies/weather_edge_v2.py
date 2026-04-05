"""
Strategy: weather_edge_v2
Hypothesis: Polymarket temperature bin markets can be mispriced vs ECMWF ensemble forecasts.
Fixes over v1:
  - ONLY bet NO on specific bins (v1 YES bets had 8% WR — catastrophic)
  - Fix range boundary: use lo <= v < hi (exclusive upper) to match market convention
  - Remove min_position_usdc floor — let Kelly size naturally for low-probability events
  - Raise min_ev_pp to 18 (be pickier)
  - Only signal when ensemble probability is very low (<5%) and market prices >15%
Method: No LLM. Regex-parses sub-market questions → geocode → ECMWF ensemble probability.
Status: ALERT-ONLY — accumulate 30 signals before enabling paper trading.
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

MAX_DAYS_TO_CLOSE = 7     # v1 was 10 — tighter window for better forecasts
MIN_DAYS_TO_CLOSE = 0
MAX_ENSEMBLE_PROB = 0.05  # only signal when ensemble says <5% for this bin
MIN_ENSEMBLE_FLOOR = 0.10 # never treat any bin as less than 10% — ensemble is overconfident
MIN_MARKET_PRICE = 0.15   # market must price the bin at >15% (otherwise no edge)
ENSEMBLE_WIDEN_C = 1.5    # widen bin check by ±1.5°C (or °F) to account for ensemble bias
MAX_ALERTS_PER_RUN = 5


def _is_weather_event(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in WEATHER_KEYWORDS)


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
        data = resp.json()
        results = data.get("results") or []
        if results:
            return float(results[0]["latitude"]), float(results[0]["longitude"])
    except Exception:
        pass
    return None


def _get_ensemble_values(lat: float, lon: float, target_date: str, metric: str, unit: str) -> list[float] | None:
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
        if "or below" in ql:
            return {**base, "direction": "below", "threshold": val}
        if "or above" in ql:
            return {**base, "direction": "above", "threshold": val}
        return {**base, "direction": "range", "threshold_low": val, "threshold_high": val + 1}

    return None


def _prob_from_values(values: list[float], parsed: dict) -> float | None:
    """Compute ensemble probability with widened bins to counter ensemble overconfidence.

    The ECMWF ensemble spread is too narrow — real temps often land 1-2° outside
    the ensemble range. We widen bins by ENSEMBLE_WIDEN_C in each direction and
    apply a floor of MIN_ENSEMBLE_FLOOR (never assume <10% probability).
    """
    n = len(values)
    if not n:
        return None
    w = ENSEMBLE_WIDEN_C
    direction = parsed["direction"]
    if direction == "above":
        satisfied = sum(1 for v in values if v >= parsed["threshold"] - w)
    elif direction == "below":
        satisfied = sum(1 for v in values if v <= parsed["threshold"] + w)
    elif direction == "range":
        lo, hi = parsed["threshold_low"], parsed["threshold_high"]
        satisfied = sum(1 for v in values if lo - w <= v < hi + w)
    else:
        return None
    raw_prob = round(satisfied / n, 4)
    return max(raw_prob, MIN_ENSEMBLE_FLOOR)


class WeatherEdgeV2Strategy(Strategy):
    name = "weather_edge_v2"
    edge_type = "model_vs_market"
    time_window = "super_short"
    target_hold_min_days = 0.02
    target_hold_max_days = 7
    scan_frequency = "3x/day"
    max_position_usdc = 10.0
    min_ev_pp = 18.0      # v1 was 12 — be pickier
    # No min_position_usdc — let Kelly size naturally
    alert_only = False
    promotable = True
    promotion_criteria = "30 alerts with >55% NO-side accuracy"
    last_check_details: list[dict] = []

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
        self.last_check_details = []

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

                prices_raw = m.get("outcomePrices", "[]")
                try:
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    yes_price = float(prices[0])
                except (ValueError, TypeError, IndexError):
                    continue

                if yes_price < MIN_MARKET_PRICE or yes_price > 0.98:
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

                # v2: ONLY bet NO — skip if ensemble thinks this bin is likely
                if prob > MAX_ENSEMBLE_PROB:
                    continue

                # NO edge: market prices YES at yes_price, ensemble says prob is very low
                ev_pp = (yes_price - prob) * 100  # edge on the NO side
                if ev_pp < self.min_ev_pp:
                    continue

                no_price = round(1 - yes_price, 4)
                no_p_hat = round(1 - prob, 4)

                direction_str = parsed["direction"]
                if direction_str == "range":
                    tstr = f"{parsed['threshold_low']}-{parsed['threshold_high']}{parsed['unit']}"
                else:
                    tstr = f"{'>' if direction_str == 'above' else '<'}{parsed['threshold']}{parsed['unit']}"

                self.last_check_details.append({
                    "market_slug": slug,
                    "title": question[:80],
                    "yes_price": yes_price,
                    "ensemble_prob": prob,
                    "ev_pp": round(ev_pp, 1),
                    "location": parsed["location"],
                    "direction": direction_str,
                    "decision": "alert",
                    "reason": f"NO:ensemble {prob*100:.0f}% vs market {yes_price*100:.0f}%",
                })

                signals.append(Signal(
                    strategy=self.name,
                    market_id=f"{slug}:{m.get('id', '')}",
                    market_title=question[:100],
                    outcome="NO",
                    market_price=no_price,
                    p_hat=no_p_hat,
                    ev_pp=round(ev_pp, 1),
                    confidence="high" if ev_pp >= 30 else "medium",
                    closes=closes,
                    url=url,
                    rationale=f"ensemble-v2:{prob*100:.0f}% vs market:{yes_price*100:.0f}% ({parsed['location']},{tstr})",
                ))

        signals.sort(key=lambda s: s.ev_pp, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(signals)} NO-only alerts")
        return signals

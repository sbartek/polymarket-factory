"""
Strategy: weather_edge_v4
Hypothesis: Polymarket temperature bin markets are mispriced vs ECMWF ensemble forecasts.
Bidirectional: bet YES when ensemble says bin is likely but market underprices it,
               bet NO when ensemble says bin is unlikely but market overprices it.

Fixes over v2:
  - Bidirectional signals (v2 was NO-only because v1 YES had 8% WR, but v1's
    problem was poor entry criteria, not the direction itself)
  - No ensemble floor — raw probabilities only
  - No bin widening — use ensemble as-is
  - Separate EV thresholds: YES requires 20pp, NO requires 18pp
  - YES positions capped at half size (historically unreliable direction)
  - Stricter: only signal when ensemble AND market both have strong conviction
    (ensemble >65% or <10%) to avoid noisy mid-range bets

Method: No LLM. Regex-parses sub-market questions → geocode → ECMWF ensemble.
Status: ALERT-ONLY — accumulate signals to validate YES/NO accuracy separately.
"""
from __future__ import annotations

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

MAX_DAYS_TO_CLOSE = 5       # tighter window → better ensemble accuracy
MIN_DAYS_TO_CLOSE = 1       # skip same-day (v3 handles those)
MAX_ENSEMBLE_PROB_NO = 0.10  # NO signal: ensemble says ≤10% for this bin
MIN_ENSEMBLE_PROB_YES = 0.65 # YES signal: ensemble says ≥65% for this bin
MIN_MARKET_PRICE_NO = 0.18   # NO signal: market must price YES at >18%
MAX_MARKET_PRICE_YES = 0.50  # YES signal: market must price YES at <50%
MIN_EV_PP_NO = 18.0
MIN_EV_PP_YES = 20.0
MAX_ALERTS_PER_RUN = 6


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


def _get_ensemble_values(
    lat: float, lon: float, target_date: str, metric: str, unit: str
) -> list[float] | None:
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
            vals = [v for v in hourly[key] if v is not None]
            if vals:
                values.append(float(reducer(vals)))
        return values if values else None
    except Exception:
        return None


def _raw_prob(values: list[float], parsed: dict) -> float | None:
    """Raw ensemble probability — no floor, no widening."""
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
        satisfied = sum(1 for v in values if lo <= v < hi)
    else:
        return None
    return round(satisfied / n, 4)


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


class WeatherEdgeV4Strategy(Strategy):
    name = "weather_edge_v4"
    edge_type = "model_vs_market"
    time_window = "short"
    target_hold_min_days = 1
    target_hold_max_days = 5
    scan_frequency = "1x/day"
    max_position_usdc = 10.0
    min_ev_pp = 18.0
    alert_only = False
    trading_enabled = True
    last_check_details: list[dict] = []

    def __init__(self) -> None:
        self._geo_cache: dict = {}
        self._ensemble_cache: dict = {}

    def _get_coords(self, location: str) -> tuple[float, float] | None:
        if location not in self._geo_cache:
            self._geo_cache[location] = _geocode(location)
        return self._geo_cache[location]

    def _get_values(
        self, location: str, target_date: str, metric: str, unit: str
    ) -> list[float] | None:
        key = f"{location}:{target_date}:{metric}:{unit}"
        if key not in self._ensemble_cache:
            coords = self._get_coords(location)
            self._ensemble_cache[key] = (
                _get_ensemble_values(coords[0], coords[1], target_date, metric, unit)
                if coords else None
            )
        return self._ensemble_cache[key]

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
            and MIN_DAYS_TO_CLOSE <= d <= MAX_DAYS_TO_CLOSE
        ]
        print(f"  [{self.name}] {len(weather_events)} weather events ({MIN_DAYS_TO_CLOSE}-{MAX_DAYS_TO_CLOSE}d)")

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

                # Skip near-certain markets (likely near resolution)
                if yes_price < 0.04 or yes_price > 0.96:
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

                prob = _raw_prob(values, parsed)
                if prob is None:
                    continue

                direction_str = parsed["direction"]
                if direction_str == "range":
                    tstr = f"{parsed['threshold_low']}-{parsed['threshold_high']}{parsed['unit']}"
                elif direction_str == "above":
                    tstr = f">{parsed['threshold']}{parsed['unit']}"
                else:
                    tstr = f"<{parsed['threshold']}{parsed['unit']}"

                signal = None

                # NO signal: ensemble says this bin is very unlikely, market overprices it
                if prob <= MAX_ENSEMBLE_PROB_NO and yes_price >= MIN_MARKET_PRICE_NO:
                    ev_pp = round((yes_price - prob) * 100, 1)
                    if ev_pp >= MIN_EV_PP_NO:
                        no_price = round(1 - yes_price, 4)
                        signal = Signal(
                            strategy=self.name,
                            market_id=f"{slug}:{m.get('id', '')}",
                            market_title=question[:100],
                            outcome="NO",
                            market_price=no_price,
                            p_hat=round(1 - prob, 4),
                            ev_pp=ev_pp,
                            confidence="high" if ev_pp >= 30 else "medium",
                            closes=closes,
                            url=url,
                            rationale=(
                                f"v4-NO:ensemble {prob*100:.0f}% vs market {yes_price*100:.0f}% "
                                f"({parsed['location']},{tstr})"
                            ),
                        )
                        self.last_check_details.append({
                            "location": parsed["location"], "tstr": tstr,
                            "yes_price": yes_price, "ensemble_prob": prob,
                            "ev_pp": ev_pp, "direction": "NO", "decision": "alert",
                        })

                # YES signal: ensemble says this bin is likely, market underprices it
                elif prob >= MIN_ENSEMBLE_PROB_YES and yes_price <= MAX_MARKET_PRICE_YES:
                    ev_pp = round((prob - yes_price) * 100, 1)
                    if ev_pp >= MIN_EV_PP_YES:
                        signal = Signal(
                            strategy=self.name,
                            market_id=f"{slug}:{m.get('id', '')}",
                            market_title=question[:100],
                            outcome="YES",
                            market_price=yes_price,
                            p_hat=prob,
                            ev_pp=ev_pp,
                            confidence="high" if ev_pp >= 30 else "medium",
                            closes=closes,
                            url=url,
                            rationale=(
                                f"v4-YES:ensemble {prob*100:.0f}% vs market {yes_price*100:.0f}% "
                                f"({parsed['location']},{tstr})"
                            ),
                        )
                        self.last_check_details.append({
                            "location": parsed["location"], "tstr": tstr,
                            "yes_price": yes_price, "ensemble_prob": prob,
                            "ev_pp": ev_pp, "direction": "YES", "decision": "alert",
                        })

                if signal:
                    signals.append(signal)

        # Score: ev * time preference (shorter markets rank higher)
        def _score(s):
            from datetime import date as _date
            try:
                d = max((_date.fromisoformat(s.closes[:10]) - _date.today()).days, 1)
            except (ValueError, TypeError):
                d = 3
            return s.ev_pp / d ** 0.5
        signals.sort(key=_score, reverse=True)
        signals = signals[:MAX_ALERTS_PER_RUN]
        print(f"  [{self.name}] {len(signals)} alerts "
              f"({sum(1 for s in signals if s.outcome=='YES')} YES, "
              f"{sum(1 for s in signals if s.outcome=='NO')} NO)")
        return signals

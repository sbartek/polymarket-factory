"""Strategy metadata helpers: edge types, time windows, and registry lookup."""
from __future__ import annotations

from typing import Literal

TimeWindow = Literal["super_short", "intraday", "short", "medium", "long"]
EdgeType = Literal[
    "information",
    "structural",
    "resolution_lag",
    "stale_repricing",
    "logical_inconsistency",
    "model_vs_market",
    "statistical_fade",
    "other",
]

TIME_WINDOW_LABELS = {
    "super_short": "<1h",
    "intraday": "1h–24h",
    "short": "1–7d",
    "medium": "8–30d",
    "long": "31d+",
}

TIME_WINDOW_EXPOSURE_CAPS = {
    "super_short": 40.0,
    "intraday": 60.0,
    "short": 120.0,
    "medium": 150.0,
    "long": 100.0,
}

STRATEGY_EXPOSURE_CAPS = {
    "spread_arb": 80.0,
    "ev_news": 40.0,
    "resolution_hunter": 0.0,  # killed — -92.3% ROI on 12 trades
    "stale_market": 35.0,
    "correlated_pairs": 30.0,
    "correlated_laggard": 0.0,
    "esport48": 0.0,
    "celebrity_tabloid": 25.0,
    "carry_rewards": 0.0,  # alert_only — no paper positions opened
}

ACTIVE_STRATEGIES = {"ev_news", "spread_arb", "stale_market", "correlated_pairs", "correlated_laggard", "esport48", "celebrity_tabloid", "carry_rewards"}


def expected_window_from_days(min_days: float | int, max_days: float | int) -> TimeWindow:
    if max_days <= (1 / 24):
        return "super_short"
    if max_days <= 1:
        return "intraday"
    if max_days <= 7:
        return "short"
    if max_days <= 30:
        return "medium"
    return "long"


STATIC_STRATEGY_METADATA = {
    "fade_certainty": {
        "name": "fade_certainty",
        "edge_type": "statistical_fade",
        "time_window": "medium",
        "time_window_label": TIME_WINDOW_LABELS["medium"],
        "target_hold_min_days": 7,
        "target_hold_max_days": 30,
        "scan_frequency": "paused",
        "paused": True,
    },
    "weather_edge": {
        "name": "weather_edge",
        "edge_type": "model_vs_market",
        "time_window": "super_short",
        "time_window_label": TIME_WINDOW_LABELS["super_short"],
        "target_hold_min_days": 0.02,
        "target_hold_max_days": 0.5,
        "scan_frequency": "paused",
        "paused": True,
    },
}


def should_run_in_cycle(time_window: str, hour: int) -> bool:
    """
    Base scheduler cadence is ~3x/day around 09 / 14 / 19 local time.
    Strategy participation should depend on the expected holding window:

    - super_short / intraday: every cycle
    - short: every cycle
    - medium: morning + evening only
    - long: morning only
    """
    if time_window in ("super_short", "intraday", "short"):
        return True
    if time_window == "medium":
        return hour in (9, 19)
    if time_window == "long":
        return hour == 9
    return True


def strategy_metadata() -> dict[str, dict]:
    from .strategies import STRATEGIES

    meta = dict(STATIC_STRATEGY_METADATA)
    for s in STRATEGIES:
        time_window = getattr(s, "time_window", None) or expected_window_from_days(
            getattr(s, "target_hold_min_days", 0),
            getattr(s, "target_hold_max_days", 30),
        )
        meta[s.name] = {
            "name": s.name,
            "edge_type": getattr(s, "edge_type", "other"),
            "time_window": time_window,
            "time_window_label": TIME_WINDOW_LABELS.get(time_window, time_window),
            "target_hold_min_days": getattr(s, "target_hold_min_days", 0),
            "target_hold_max_days": getattr(s, "target_hold_max_days", 30),
            "scan_frequency": getattr(s, "scan_frequency", "manual"),
            "paused": getattr(s, "paused", False),
            "alert_only": getattr(s, "alert_only", False),
            "trading_enabled": getattr(s, "trading_enabled", not getattr(s, "alert_only", False)),
            "promotable": getattr(s, "promotable", False),
            "live_ready": getattr(s, "live_ready", False),
            "promotion_candidate": bool(getattr(s, "alert_only", False) and getattr(s, "promotable", False)),
            "promotion_criteria": getattr(s, "promotion_criteria", ""),
            "window_exposure_cap": TIME_WINDOW_EXPOSURE_CAPS.get(time_window),
            "strategy_exposure_cap": STRATEGY_EXPOSURE_CAPS.get(getattr(s, 'name', ''), 50.0),
        }
    return meta

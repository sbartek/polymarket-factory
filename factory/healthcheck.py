"""Dead man's switch monitoring — file-based heartbeats + Slack alerts.

Each cron job calls ping() on success/failure, which writes a timestamp file
to data/heartbeats/<slug>.json. A separate watchdog (check_heartbeats) runs
via cron every 10 min and alerts Slack if any job is overdue.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

HEARTBEAT_DIR = Path(os.environ.get("FACTORY_DATA_DIR", "data")) / "heartbeats"

# slug -> (expected period in minutes, grace in minutes)
SCHEDULES: dict[str, tuple[int, int]] = {
    "scan":             (120, 30),
    "execute":          (120, 30),
    "observer":         (30,  15),
    "trade-fetcher":    (30,  15),
    "strategy-factory": (1440, 60),
    "live":             (1440, 60),
    "research":         (1440, 60),
    "backup":           (1440, 60),
}


def ping(slug: str, *, success: bool = True) -> None:
    """Record a heartbeat for the given job slug."""
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    path = HEARTBEAT_DIR / f"{slug}.json"
    data = {
        "slug": slug,
        "success": success,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(data))


def check_heartbeats() -> list[dict]:
    """Check all registered jobs for overdue heartbeats.

    Returns a list of dicts for jobs that are overdue or have never reported.
    """
    now = datetime.now(UTC)
    problems: list[dict] = []

    for slug, (period_min, grace_min) in SCHEDULES.items():
        path = HEARTBEAT_DIR / f"{slug}.json"
        if not path.exists():
            problems.append({
                "slug": slug,
                "status": "never_reported",
                "detail": "no heartbeat file found",
            })
            continue

        try:
            data = json.loads(path.read_text())
            ts = datetime.fromisoformat(data["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            age = now - ts
            deadline = timedelta(minutes=period_min + grace_min)

            if age > deadline:
                hours = age.total_seconds() / 3600
                problems.append({
                    "slug": slug,
                    "status": "overdue",
                    "detail": f"last ping {hours:.1f}h ago, expected every {period_min}m +{grace_min}m grace",
                    "last_success": data.get("success", True),
                })
            elif not data.get("success", True):
                problems.append({
                    "slug": slug,
                    "status": "failed",
                    "detail": f"last run failed at {data['timestamp']}",
                    "last_success": False,
                })
        except (json.JSONDecodeError, KeyError, ValueError):
            problems.append({
                "slug": slug,
                "status": "corrupt",
                "detail": f"could not parse {path}",
            })

    return problems

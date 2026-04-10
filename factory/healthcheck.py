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

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SIGNAL_REPEAT_WINDOW_HOURS = 24
SIGNAL_REPEAT_THRESHOLD = 2.5  # avg signals per unique market above this triggers alert

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


def ping(slug: str, *, success: bool = True, status: str = "ok", detail: str | None = None) -> None:
    """Record a heartbeat for the given job slug."""
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    path = HEARTBEAT_DIR / f"{slug}.json"
    data = {
        "slug": slug,
        "success": success,
        "status": status,
        "detail": detail,
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
            elif data.get("status") == "degraded":
                problems.append({
                    "slug": slug,
                    "status": "degraded",
                    "detail": data.get("detail") or f"last run degraded at {data['timestamp']}",
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


def check_signal_repeats(dsn: str | None = None) -> list[dict]:
    """Check for strategies re-firing on the same markets excessively.

    Returns a list of dicts for strategies whose signals/unique_market ratio
    exceeds SIGNAL_REPEAT_THRESHOLD over the last SIGNAL_REPEAT_WINDOW_HOURS.
    """
    dsn = dsn or DATABASE_URL
    if not dsn:
        return []
    problems: list[dict] = []
    cutoff = (datetime.now(UTC) - timedelta(hours=SIGNAL_REPEAT_WINDOW_HOURS)).isoformat(timespec="seconds")
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            """
            SELECT strategy,
                   COUNT(*) AS total,
                   COUNT(DISTINCT market_id) AS unique_markets,
                   ROUND(CAST(COUNT(*) AS NUMERIC) / COUNT(DISTINCT market_id), 2) AS ratio
            FROM signals
            WHERE created_at >= %s
            GROUP BY strategy
            HAVING ROUND(CAST(COUNT(*) AS NUMERIC) / COUNT(DISTINCT market_id), 2) > %s AND COUNT(*) >= 5
            ORDER BY ratio DESC
            """,
            (cutoff, SIGNAL_REPEAT_THRESHOLD),
        )
        rows = cur.fetchall()
        conn.close()
        for row in rows:
            problems.append({
                "slug": f"signal-repeat:{row['strategy']}",
                "status": "signal_repeat",
                "detail": (
                    f"{row['total']} signals / {row['unique_markets']} unique markets "
                    f"= {row['ratio']}x repeat (last {SIGNAL_REPEAT_WINDOW_HOURS}h, "
                    f"threshold {SIGNAL_REPEAT_THRESHOLD}x)"
                ),
            })
    except Exception as e:
        problems.append({
            "slug": "signal-repeat-check",
            "status": "corrupt",
            "detail": f"could not query signals: {e}",
        })
    return problems

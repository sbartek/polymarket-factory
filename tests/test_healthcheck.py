"""Tests for file-based healthcheck (heartbeat + watchdog)."""
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from factory.healthcheck import HEARTBEAT_DIR, check_heartbeats, ping


def test_ping_creates_heartbeat_file(tmp_path):
    with patch("factory.healthcheck.HEARTBEAT_DIR", tmp_path):
        ping("scan")
        path = tmp_path / "scan.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["slug"] == "scan"
        assert data["success"] is True


def test_ping_failure(tmp_path):
    with patch("factory.healthcheck.HEARTBEAT_DIR", tmp_path):
        ping("scan", success=False)
        data = json.loads((tmp_path / "scan.json").read_text())
        assert data["success"] is False


def test_check_heartbeats_all_fresh(tmp_path):
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with patch("factory.healthcheck.HEARTBEAT_DIR", tmp_path):
        for slug in ("scan", "execute", "observer", "trade-fetcher",
                     "strategy-factory", "live", "research", "backup"):
            (tmp_path / f"{slug}.json").write_text(
                json.dumps({"slug": slug, "success": True, "timestamp": now})
            )
        problems = check_heartbeats()
        assert problems == []


def test_check_heartbeats_detects_overdue(tmp_path):
    old = (datetime.now(UTC) - timedelta(hours=5)).isoformat(timespec="seconds")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with patch("factory.healthcheck.HEARTBEAT_DIR", tmp_path):
        # scan is overdue (5h old, expected every 2h + 30m grace)
        (tmp_path / "scan.json").write_text(
            json.dumps({"slug": "scan", "success": True, "timestamp": old})
        )
        # all others are fresh
        for slug in ("execute", "observer", "trade-fetcher",
                     "strategy-factory", "live", "research", "backup"):
            (tmp_path / f"{slug}.json").write_text(
                json.dumps({"slug": slug, "success": True, "timestamp": now})
            )
        problems = check_heartbeats()
        assert len(problems) == 1
        assert problems[0]["slug"] == "scan"
        assert problems[0]["status"] == "overdue"


def test_check_heartbeats_detects_never_reported(tmp_path):
    with patch("factory.healthcheck.HEARTBEAT_DIR", tmp_path):
        # no files at all
        problems = check_heartbeats()
        slugs = {p["slug"] for p in problems}
        assert "scan" in slugs
        assert all(p["status"] == "never_reported" for p in problems)


def test_check_heartbeats_detects_failure(tmp_path):
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with patch("factory.healthcheck.HEARTBEAT_DIR", tmp_path):
        for slug in ("scan", "execute", "observer", "trade-fetcher",
                     "strategy-factory", "live", "research", "backup"):
            success = slug != "backup"  # backup failed
            (tmp_path / f"{slug}.json").write_text(
                json.dumps({"slug": slug, "success": success, "timestamp": now})
            )
        problems = check_heartbeats()
        assert len(problems) == 1
        assert problems[0]["slug"] == "backup"
        assert problems[0]["status"] == "failed"

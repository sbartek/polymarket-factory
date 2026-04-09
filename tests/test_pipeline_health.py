"""Tests for pipeline health monitoring."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from factory.db import FactoryDB


class _FakeCursor:
    def __init__(self, rows_by_mode: dict[str, dict | None]):
        self.rows_by_mode = rows_by_mode
        self.current = None

    def execute(self, _sql, params):
        self.current = self.rows_by_mode.get(params[0])

    def fetchone(self):
        return self.current


def _make_db(rows_by_mode: dict[str, dict | None]):
    db = FactoryDB.__new__(FactoryDB)

    @contextmanager
    def fake_conn():
        yield None, _FakeCursor(rows_by_mode)

    db._conn = fake_conn
    return db


class TestGetPipelineHealth:
    def test_never_run_pipelines(self):
        db = _make_db({})
        health = db.get_pipeline_health()
        assert len(health) == 4
        for p in health:
            assert p["status"] == "never_run"
            assert p["overdue"] is True

    def test_recent_run_not_overdue(self):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        db = _make_db({
            "observer": {
                "finished_at": now,
                "status": "success",
            }
        })
        health = db.get_pipeline_health()
        observer = next(p for p in health if p["name"] == "observer")
        assert observer["status"] == "success"
        assert observer["overdue"] is False
        assert observer["age_minutes"] >= 0

    def test_failed_run_shows_status(self):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        db = _make_db({
            "trade_fetcher": {
                "finished_at": now,
                "status": "failed",
            }
        })
        health = db.get_pipeline_health()
        fetcher = next(p for p in health if p["name"] == "trade_fetcher")
        assert fetcher["status"] == "failed"
        assert fetcher["overdue"] is False


class TestPipelineHealthInSummary:
    def test_overdue_pipelines_shown(self):
        from factory.runner import format_wa_summary
        health = [
            {"name": "observer", "last_run": "2026-04-04T10:00:00+00:00", "status": "success", "age_minutes": 120, "overdue": True},
            {"name": "trade_fetcher", "last_run": None, "status": "never_run", "age_minutes": None, "overdue": True},
            {"name": "scanner", "last_run": "2026-04-04T17:00:00+00:00", "status": "success", "age_minutes": 10, "overdue": False},
        ]
        msg = format_wa_summary([], [], [], 0, {"strategies": {}}, "2026-04-04 19:00", hour=14, pipeline_health=health)
        assert "PIPELINE ALERTS" in msg
        assert "observer" in msg
        assert "trade_fetcher" in msg
        assert "scanner" not in msg.split("PIPELINE ALERTS")[1]

    def test_no_alert_when_all_ok(self):
        from factory.runner import format_wa_summary
        health = [
            {"name": "observer", "last_run": "2026-04-04T18:50:00+00:00", "status": "success", "age_minutes": 10, "overdue": False},
        ]
        msg = format_wa_summary([], [], [], 0, {"strategies": {}}, "2026-04-04 19:00", hour=14, pipeline_health=health)
        assert "PIPELINE ALERTS" not in msg

    def test_no_alert_section_when_no_health_data(self):
        from factory.runner import format_wa_summary
        msg = format_wa_summary([], [], [], 0, {"strategies": {}}, "2026-04-04 14:00", hour=14, pipeline_health=None)
        assert "PIPELINE" not in msg

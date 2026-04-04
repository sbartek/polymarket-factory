"""Tests for pipeline health monitoring."""
import tempfile
from pathlib import Path

from factory.db import FactoryDB


def _make_db():
    return FactoryDB(path=Path(tempfile.mktemp(suffix=".db")))


class TestGetPipelineHealth:
    def test_never_run_pipelines(self):
        db = _make_db()
        health = db.get_pipeline_health()
        assert len(health) == 5
        for p in health:
            assert p["status"] == "never_run"
            assert p["overdue"] is True

    def test_recent_run_not_overdue(self):
        db = _make_db()
        run_id = db.start_run(mode="observer")
        db.finish_run(run_id, status="success")
        health = db.get_pipeline_health()
        observer = next(p for p in health if p["name"] == "observer")
        assert observer["status"] == "success"
        assert observer["overdue"] is False
        assert observer["age_minutes"] < 2

    def test_failed_run_shows_status(self):
        db = _make_db()
        run_id = db.start_run(mode="trade_fetcher")
        db.finish_run(run_id, status="failed")
        health = db.get_pipeline_health()
        fetcher = next(p for p in health if p["name"] == "trade_fetcher")
        assert fetcher["status"] == "failed"
        assert fetcher["overdue"] is False  # just ran, not overdue yet


class TestPipelineHealthInSummary:
    def test_overdue_pipelines_shown(self):
        from factory.runner import format_wa_summary
        health = [
            {"name": "observer", "last_run": "2026-04-04T10:00:00+00:00", "status": "success", "age_minutes": 120, "overdue": True},
            {"name": "trade_fetcher", "last_run": None, "status": "never_run", "age_minutes": None, "overdue": True},
            {"name": "combined", "last_run": "2026-04-04T17:00:00+00:00", "status": "success", "age_minutes": 10, "overdue": False},
        ]
        msg = format_wa_summary([], [], [], 0, {"strategies": {}}, "2026-04-04 19:00", hour=14, pipeline_health=health)
        assert "PIPELINE ALERTS" in msg
        assert "observer" in msg
        assert "trade_fetcher" in msg
        assert "combined" not in msg.split("PIPELINE ALERTS")[1]  # combined is OK

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

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import scripts.strategy_factory_local_runner as runner


def test_file_lock_acquires_and_releases(tmp_path, monkeypatch):
    lock_dir = tmp_path / "locks"
    lock_path = lock_dir / "strategy-factory-local.lock"
    monkeypatch.setattr(runner, "LOCK_DIR", lock_dir)
    monkeypatch.setattr(runner, "LOCK_PATH", lock_path)

    with runner.file_lock():
        assert lock_path.exists()

    assert not lock_path.exists()


def test_file_lock_replaces_stale_lock(tmp_path, monkeypatch):
    lock_dir = tmp_path / "locks"
    lock_path = lock_dir / "strategy-factory-local.lock"
    lock_dir.mkdir(parents=True)
    lock_path.write_text(json.dumps({"acquired_at_epoch": time.time() - 999999}), encoding="utf-8")
    monkeypatch.setattr(runner, "LOCK_DIR", lock_dir)
    monkeypatch.setattr(runner, "LOCK_PATH", lock_path)

    with runner.file_lock():
        assert lock_path.exists()


def test_file_lock_rejects_active_lock(tmp_path, monkeypatch):
    lock_dir = tmp_path / "locks"
    lock_path = lock_dir / "strategy-factory-local.lock"
    lock_dir.mkdir(parents=True)
    lock_path.write_text(json.dumps({"acquired_at_epoch": time.time()}), encoding="utf-8")
    monkeypatch.setattr(runner, "LOCK_DIR", lock_dir)
    monkeypatch.setattr(runner, "LOCK_PATH", lock_path)

    with pytest.raises(RuntimeError, match="already active"):
        with runner.file_lock():
            pass


def test_write_run_record_updates_latest(tmp_path, monkeypatch):
    run_dir = tmp_path / "strategy-factory-runs"
    monkeypatch.setattr(runner, "RUN_LOG_DIR", run_dir)
    record = {"started_at": "2026-04-10T09:30:00+00:00", "status": "ok"}

    runner.write_run_record(record)

    latest = json.loads((run_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["status"] == "ok"
    files = [p for p in run_dir.glob("strategy-factory-*.json")]
    assert len(files) == 1


def test_build_status_message_includes_error():
    message = runner.build_status_message({
        "status": "failed",
        "started_at": "2026-04-10T09:30:00+00:00",
        "finished_at": "2026-04-10T09:31:00+00:00",
        "eval_source": "cache",
        "generated_count": 2,
        "archived_count": 1,
        "error": "git push failed",
    })

    assert "Strategy factory failed" in message
    assert "eval_source: cache" in message
    assert "error: git push failed" in message


def test_notify_if_needed_sends_for_degraded(monkeypatch):
    sent = []
    monkeypatch.setattr(runner, "send_slack", lambda text: sent.append(text) or True)

    runner.notify_if_needed({
        "status": "degraded",
        "started_at": "2026-04-10T09:30:00+00:00",
        "finished_at": "2026-04-10T09:31:00+00:00",
        "eval_source": "cache",
        "generated_count": 2,
        "archived_count": 0,
    })

    assert len(sent) == 1
    assert "Strategy factory degraded" in sent[0]


def test_notify_if_needed_skips_ok(monkeypatch):
    sent = []
    monkeypatch.setattr(runner, "send_slack", lambda text: sent.append(text) or True)

    runner.notify_if_needed({"status": "ok"})

    assert sent == []

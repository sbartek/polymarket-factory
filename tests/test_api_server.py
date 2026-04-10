from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import HTTPException

import api.server as server


def test_ready_reports_success(monkeypatch):
    class _Conn:
        def close(self):
            return None

    monkeypatch.setenv("FACTORY_API_KEY", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://example")
    monkeypatch.setattr(server, "PROJECT_ROOT", Path(__file__).resolve().parents[1])
    monkeypatch.setattr(server.psycopg2, "connect", lambda *args, **kwargs: _Conn())

    response = server.ready()

    assert response.status_code == 200
    assert b'"status":"ready"' in response.body


def test_ready_reports_db_failure(monkeypatch):
    monkeypatch.setenv("FACTORY_API_KEY", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://example")
    monkeypatch.setattr(server, "PROJECT_ROOT", Path(__file__).resolve().parents[1])
    monkeypatch.setattr(server.psycopg2, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))

    response = server.ready()

    assert response.status_code == 503
    assert b'"status":"not_ready"' in response.body
    assert b'db down' in response.body


def test_get_eval_logs_and_raises_on_timeout(tmp_path, monkeypatch):
    log_file = tmp_path / "eval-errors.log"

    monkeypatch.setattr(server, "EVAL_ERROR_LOG", log_file)
    monkeypatch.setattr(server, "API_LOG_DIR", tmp_path)
    monkeypatch.setattr(server, "EVAL_TIMEOUT_SECONDS", 9)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", ["eval"]), timeout=9)

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    try:
        server.get_eval()
    except HTTPException as exc:
        assert exc.status_code == 504
        assert exc.detail == "eval_subprocess_timeout after 9s"
    else:
        raise AssertionError("expected HTTPException")

    text = log_file.read_text(encoding="utf-8")
    assert "eval_subprocess_timeout" in text


def test_get_eval_logs_and_raises_on_subprocess_failure(tmp_path, monkeypatch):
    log_file = tmp_path / "eval-errors.log"

    monkeypatch.setattr(server, "EVAL_ERROR_LOG", log_file)
    monkeypatch.setattr(server, "API_LOG_DIR", tmp_path)

    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["python", "eval/report.py"],
            returncode=1,
            stdout="",
            stderr="database missing",
        ),
    )

    try:
        server.get_eval()
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "eval_subprocess_failed: database missing"
    else:
        raise AssertionError("expected HTTPException")

    text = log_file.read_text(encoding="utf-8")
    assert "eval_subprocess_failed" in text
    assert "database missing" in text

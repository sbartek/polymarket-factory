from __future__ import annotations

import importlib.util
import socket
import urllib.error
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "strategy_factory_cycle.py"
SPEC = importlib.util.spec_from_file_location("strategy_factory_cycle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
strategy_factory_cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(strategy_factory_cycle)


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload


def test_api_get_retries_timeout_then_succeeds(monkeypatch):
    calls: list[str] = []
    sleeps: list[int] = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise socket.timeout("timed out")
        return _FakeResponse(b"ok")

    monkeypatch.setattr(strategy_factory_cycle, "REMOTE_API_URL", "https://factory.example")
    monkeypatch.setattr(strategy_factory_cycle.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(strategy_factory_cycle.time, "sleep", lambda delay: sleeps.append(delay))

    result = strategy_factory_cycle._api_get("/eval", timeout=5)

    assert result == b"ok"
    assert calls == [
        "https://factory.example/eval",
        "https://factory.example/eval",
        "https://factory.example/eval",
    ]
    assert sleeps == [2, 5]


def test_api_get_does_not_retry_non_retryable_http_error(monkeypatch):
    calls: list[str] = []
    sleeps: list[int] = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 404, "not found", hdrs=None, fp=None)

    monkeypatch.setattr(strategy_factory_cycle, "REMOTE_API_URL", "https://factory.example")
    monkeypatch.setattr(strategy_factory_cycle.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(strategy_factory_cycle.time, "sleep", lambda delay: sleeps.append(delay))

    try:
        strategy_factory_cycle._api_get("/missing", timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:
        raise AssertionError("expected HTTPError")

    assert calls == ["https://factory.example/missing"]
    assert sleeps == []


def test_capture_eval_report_uses_cache_when_remote_eval_fails(tmp_path, monkeypatch):
    cache_file = tmp_path / "last_eval_report.txt"
    cache_file.write_text("cached eval", encoding="utf-8")

    monkeypatch.setattr(strategy_factory_cycle, "REMOTE_API_URL", "https://factory.example")
    monkeypatch.setattr(strategy_factory_cycle, "EVAL_REPORT_CACHE", cache_file)
    monkeypatch.setattr(
        strategy_factory_cycle,
        "_api_get",
        lambda path, timeout=strategy_factory_cycle.REMOTE_API_DEFAULT_TIMEOUT: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    result = strategy_factory_cycle.capture_eval_report()

    assert result == "cached eval"


def test_capture_eval_report_writes_cache_after_remote_success(tmp_path, monkeypatch):
    cache_file = tmp_path / "last_eval_report.txt"

    monkeypatch.setattr(strategy_factory_cycle, "REMOTE_API_URL", "https://factory.example")
    monkeypatch.setattr(strategy_factory_cycle, "EVAL_REPORT_CACHE", cache_file)
    monkeypatch.setattr(
        strategy_factory_cycle,
        "_api_get",
        lambda path, timeout=strategy_factory_cycle.REMOTE_API_DEFAULT_TIMEOUT: b"fresh eval",
    )

    result = strategy_factory_cycle.capture_eval_report()

    assert result == "fresh eval"
    assert cache_file.read_text(encoding="utf-8") == "fresh eval"


def test_generation_skip_reason_when_remote_eval_falls_back_to_cache(monkeypatch):
    monkeypatch.setattr(strategy_factory_cycle, "REMOTE_API_URL", "https://factory.example")
    monkeypatch.setattr(strategy_factory_cycle, "LAST_EVAL_SOURCE", "cache")
    monkeypatch.setattr(strategy_factory_cycle, "LAST_BENCHMARK_FETCHES", [
        {"scope": "alert-only"},
        {"scope": "generated"},
    ])

    reason = strategy_factory_cycle.generation_skip_reason()

    assert reason == "remote eval unavailable; using cached eval report"


def test_generation_skip_reason_when_remote_benchmark_fetch_is_incomplete(monkeypatch):
    monkeypatch.setattr(strategy_factory_cycle, "REMOTE_API_URL", "https://factory.example")
    monkeypatch.setattr(strategy_factory_cycle, "LAST_EVAL_SOURCE", "remote")
    monkeypatch.setattr(strategy_factory_cycle, "LAST_BENCHMARK_FETCHES", [{"scope": "alert-only"}])

    reason = strategy_factory_cycle.generation_skip_reason()

    assert reason == "remote benchmark fetch incomplete"

"""Tests for call_claude timeout and circuit breaker."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from factory.claude import (
    CIRCUIT_BREAKER_THRESHOLD,
    call_claude,
    is_circuit_open,
    reset_circuit_breaker,
    _record_failure,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_circuit_breaker()
    yield
    reset_circuit_breaker()


class TestCircuitBreaker:
    def test_circuit_starts_closed(self):
        assert is_circuit_open() is False

    def test_circuit_opens_after_threshold_failures(self):
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            _record_failure()
        assert is_circuit_open() is True

    def test_call_returns_error_when_circuit_open(self):
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            _record_failure()
        result = call_claude("test prompt")
        assert "[LLM circuit breaker open" in result

    def test_reset_closes_circuit(self):
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            _record_failure()
        assert is_circuit_open() is True
        reset_circuit_breaker()
        assert is_circuit_open() is False

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False)
    def test_timeout_records_failure(self):
        import subprocess
        with patch("factory.claude.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 60)):
            result = call_claude("test", timeout=1)
        assert "[LLM call timed out" in result

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False)
    def test_repeated_timeouts_open_circuit(self):
        import subprocess
        with patch("factory.claude.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 60)):
            for _ in range(CIRCUIT_BREAKER_THRESHOLD):
                call_claude("test", timeout=1)
        assert is_circuit_open() is True
        result = call_claude("should be blocked")
        assert "[LLM circuit breaker open" in result

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=False)
    def test_api_exception_falls_through_to_cli(self):
        import subprocess
        import anthropic as anthropic_mod

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="cli response", stderr="")
        with patch.object(anthropic_mod, "Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.side_effect = Exception("API error")
            with patch("factory.claude.subprocess.run", return_value=mock_result):
                result = call_claude("test")
        assert result == "cli response"

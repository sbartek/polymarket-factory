"""Claude API wrapper — uses API key if set, falls back to local CLI, then Codex.

Includes a per-process circuit breaker: after CIRCUIT_BREAKER_THRESHOLD consecutive
failures, all subsequent calls in the same process return an error string immediately.

All LLM calls are logged to data/llm_prompts.log and data/llm_responses.log with a
shared request_id for joining.
"""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

# Circuit breaker state (per-process)
_consecutive_failures: int = 0
CIRCUIT_BREAKER_THRESHOLD: int = 3
CALL_TIMEOUT_SECONDS: int = 60

LOG_DIR = Path(__file__).resolve().parents[1] / "data"
PROMPT_LOG = LOG_DIR / "llm_prompts.log"
RESPONSE_LOG = LOG_DIR / "llm_responses.log"


def _log_prompt(request_id: str, prompt: str, method: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "request_id": request_id,
            "method": method,
            "prompt_len": len(prompt),
            "prompt": prompt[:2000],
        }
        with open(PROMPT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _log_response(request_id: str, response: str, method: str, status: str, elapsed_ms: int) -> None:
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "request_id": request_id,
            "method": method,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "response_len": len(response),
            "response": response[:2000],
        }
        with open(RESPONSE_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def reset_circuit_breaker():
    """Reset the circuit breaker — useful in tests or at start of a new run."""
    global _consecutive_failures
    _consecutive_failures = 0


def _record_success():
    global _consecutive_failures
    _consecutive_failures = 0


def _record_failure():
    global _consecutive_failures
    _consecutive_failures += 1


def is_circuit_open() -> bool:
    return _consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD


def _call_codex(prompt: str) -> str:
    result = subprocess.run(
        ["codex", "exec", prompt],
        capture_output=True, text=True,
        timeout=CALL_TIMEOUT_SECONDS,
    )
    return result.stdout.strip() or result.stderr.strip()


def call_claude(prompt: str, max_tokens: int = 2048, timeout: int | None = None) -> str:
    timeout = timeout or CALL_TIMEOUT_SECONDS
    request_id = uuid.uuid4().hex[:12]

    if is_circuit_open():
        msg = f"[LLM circuit breaker open after {_consecutive_failures} consecutive failures]"
        _log_prompt(request_id, prompt, "circuit_breaker")
        _log_response(request_id, msg, "circuit_breaker", "blocked", 0)
        return msg

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        _log_prompt(request_id, prompt, "api")
        t0 = time.monotonic()
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text
            elapsed = int((time.monotonic() - t0) * 1000)
            _record_success()
            _log_response(request_id, result_text, "api", "success", elapsed)
            return result_text
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            _record_failure()
            _log_response(request_id, str(e), "api", "error", elapsed)
            # Fall through to CLI
            pass

    _log_prompt(request_id, prompt, "cli")
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            ["claude", "--permission-mode", "bypassPermissions", "--print", prompt],
            capture_output=True, text=True,
            timeout=timeout,
        )
        output = result.stdout.strip() or result.stderr.strip()
        elapsed = int((time.monotonic() - t0) * 1000)
        # Fall back to Codex if Claude CLI hits a token/context limit
        if any(phrase in output.lower() for phrase in ("token limit", "context length", "too long", "max tokens")):
            _log_response(request_id, output, "cli", "fallback_codex", elapsed)
            t0 = time.monotonic()
            result_text = _call_codex(prompt)
            elapsed = int((time.monotonic() - t0) * 1000)
            _record_success()
            _log_response(request_id, result_text, "codex", "success", elapsed)
            return result_text
        _record_success()
        _log_response(request_id, output, "cli", "success", elapsed)
        return output
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - t0) * 1000)
        _record_failure()
        msg = f"[LLM call timed out after {timeout}s]"
        _log_response(request_id, msg, "cli", "timeout", elapsed)
        return msg
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        _record_failure()
        msg = f"[LLM call failed: {e}]"
        _log_response(request_id, msg, "cli", "error", elapsed)
        return msg

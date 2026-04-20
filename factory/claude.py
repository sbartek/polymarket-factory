"""LLM wrapper — Claude (Anthropic API) and Gemini (Vertex AI).

Claude: used for trading strategies (ev_news, stale_market, etc.) where reasoning quality matters.
Gemini Flash: used for bulk/template work (wiki generation) where cost and speed matter.

Includes a per-process circuit breaker: after CIRCUIT_BREAKER_THRESHOLD consecutive
failures, all subsequent calls in the same process return an error string immediately.

All LLM calls are logged to data/llm_prompts.log and data/llm_responses.log with a
shared request_id for joining.
"""
import json
import os
import signal
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



def _call_with_hard_timeout(fn, timeout_sec):
    """Run fn() with a SIGALRM hard timeout. Falls back gracefully on non-Unix."""
    def _handler(signum, frame):
        raise TimeoutError(f"Hard timeout after {timeout_sec}s")
    try:
        old = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout_sec)
        try:
            return fn()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    except AttributeError:
        # Windows — no SIGALRM, just call directly
        return fn()


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
    except Exception as e:
        print(f"  [claude] WARNING: failed to log prompt: {e}")


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
    except Exception as e:
        print(f"  [claude] WARNING: failed to log response: {e}")


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


def call_claude(prompt: str, max_tokens: int = 2048, timeout: int | None = None, model: str = "claude-haiku-4-5") -> str:
    timeout = timeout or CALL_TIMEOUT_SECONDS
    request_id = uuid.uuid4().hex[:12]

    if is_circuit_open():
        msg = f"[LLM circuit breaker open after {_consecutive_failures} consecutive failures]"
        _log_prompt(request_id, prompt, "circuit_breaker")
        _log_response(request_id, msg, "circuit_breaker", "blocked", 0)
        return msg

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        _log_prompt(request_id, prompt, f"api:{model}")
        t0 = time.monotonic()
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
            def _api_call():
                return client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
            response = _call_with_hard_timeout(_api_call, timeout)
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


GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_PROJECT = "pplayouts-factory"
GEMINI_LOCATION = "us-central1"


def call_gemini(prompt: str, max_tokens: int = 2048, timeout: int | None = None) -> str:
    """Call Gemini via Vertex AI. Falls back to call_claude() on failure."""
    timeout = timeout or CALL_TIMEOUT_SECONDS
    request_id = uuid.uuid4().hex[:12]

    if is_circuit_open():
        msg = f"[LLM circuit breaker open after {_consecutive_failures} consecutive failures]"
        _log_prompt(request_id, prompt, "gemini_circuit_breaker")
        _log_response(request_id, msg, "gemini_circuit_breaker", "blocked", 0)
        return msg

    _log_prompt(request_id, prompt, "gemini")
    t0 = time.monotonic()
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(vertexai=True, project=GEMINI_PROJECT, location=GEMINI_LOCATION)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        result_text = response.text or ""
        if not result_text:
            raise ValueError(f"Empty response (finish_reason={response.candidates[0].finish_reason if response.candidates else 'unknown'})")
        elapsed = int((time.monotonic() - t0) * 1000)
        _record_success()
        _log_response(request_id, result_text, "gemini", "success", elapsed)
        return result_text
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        _record_failure()
        _log_response(request_id, str(e), "gemini", "error", elapsed)
        print(f"  [gemini] Failed ({e}), falling back to Claude")
        return call_claude(prompt, max_tokens=max_tokens, timeout=timeout)

"""Claude API wrapper — uses API key if set, falls back to local CLI, then Codex.

Includes a per-process circuit breaker: after CIRCUIT_BREAKER_THRESHOLD consecutive
failures, all subsequent calls in the same process return an error string immediately.
"""
import os
import subprocess
import time

# Circuit breaker state (per-process)
_consecutive_failures: int = 0
CIRCUIT_BREAKER_THRESHOLD: int = 3
CALL_TIMEOUT_SECONDS: int = 60


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

    if is_circuit_open():
        return f"[LLM circuit breaker open after {_consecutive_failures} consecutive failures]"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            _record_success()
            return response.content[0].text
        except Exception as e:
            _record_failure()
            # Fall through to CLI
            pass

    try:
        result = subprocess.run(
            ["claude", "--permission-mode", "bypassPermissions", "--print", prompt],
            capture_output=True, text=True,
            timeout=timeout,
        )
        output = result.stdout.strip() or result.stderr.strip()
        # Fall back to Codex if Claude CLI hits a token/context limit
        if any(phrase in output.lower() for phrase in ("token limit", "context length", "too long", "max tokens")):
            result_text = _call_codex(prompt)
            _record_success()
            return result_text
        _record_success()
        return output
    except subprocess.TimeoutExpired:
        _record_failure()
        return f"[LLM call timed out after {timeout}s]"
    except Exception as e:
        _record_failure()
        return f"[LLM call failed: {e}]"

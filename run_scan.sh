#!/bin/bash
# Phase 1: scan markets and cache signals to DB.
# Run ~30min before execute phase so LLM/news calls don't block execution.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi
export FACTORY_ENV="${FACTORY_ENV:-paper}"

cd "$SCRIPT_DIR"
uv run python -m factory.scanner --limit 1000
EXIT_CODE=$?

# Healthcheck ping
PING_KEY="${HEALTHCHECKS_PING_KEY:-}"
if [[ -n "$PING_KEY" ]]; then
    if [[ $EXIT_CODE -eq 0 ]]; then
        curl -fsS -m 10 --retry 3 "https://hc-ping.com/$PING_KEY/scan" > /dev/null 2>&1 || true
    else
        curl -fsS -m 10 --retry 3 "https://hc-ping.com/$PING_KEY/scan/fail" > /dev/null 2>&1 || true
    fi
fi

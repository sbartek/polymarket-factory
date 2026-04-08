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
timeout 90m uv run python -m factory.scanner --limit 1000
EXIT_CODE=$?

# Heartbeat ping
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('scan')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('scan', success=False)" 2>/dev/null || true
fi

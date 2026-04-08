#!/bin/bash
# Lightweight price observer — fetch snapshots every 30 min for price history.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi

cd "$SCRIPT_DIR"
timeout 20m uv run python -m factory.observer --limit 1000
EXIT_CODE=$?

# Heartbeat ping
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('observer')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('observer', success=False)" 2>/dev/null || true
fi

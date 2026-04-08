#!/bin/bash
# CLOB trade data fetcher — fetch recent trades every 30 min.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi

cd "$SCRIPT_DIR"
timeout 15m uv run python -m factory.trade_fetcher --limit 5000
EXIT_CODE=$?

# Heartbeat ping
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('trade-fetcher')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('trade-fetcher', success=False)" 2>/dev/null || true
fi

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
uv run python -m factory.observer --limit 1000
EXIT_CODE=$?

# Healthcheck ping
PING_KEY="${HEALTHCHECKS_PING_KEY:-}"
if [[ -n "$PING_KEY" ]]; then
    if [[ $EXIT_CODE -eq 0 ]]; then
        curl -fsS -m 10 --retry 3 "https://hc-ping.com/$PING_KEY/observer" > /dev/null 2>&1 || true
    else
        curl -fsS -m 10 --retry 3 "https://hc-ping.com/$PING_KEY/observer/fail" > /dev/null 2>&1 || true
    fi
fi

#!/bin/bash
# Run strategy factory on Mac — fetches eval + benchmarks from VM API, no SQLite needed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
export PATH="/Users/barteks/.local/bin:$PATH"

cd "$SCRIPT_DIR"

echo "[strategy-factory-local] pulling latest repo..."
git pull

echo "[strategy-factory-local] running cycle (remote API mode)..."
FACTORY_REMOTE_API_URL="${FACTORY_REMOTE_API_URL:-https://factory.pplayouts.trade}" \
    uv run python scripts/strategy_factory_cycle.py
EXIT_CODE=$?

# Commit any newly generated strategy files
git add factory/strategies/generated/ improvement/proposals/ dashboard-data/ benchmark-data/ 2>/dev/null || true
if ! git diff --staged --quiet; then
    git commit -m "strategy factory: auto-generated strategies $(date +%Y-%m-%d)"
    git push
    echo "[strategy-factory-local] pushed new strategies to repo"
fi

# Ping heartbeat to VM so watchdog knows it ran
if [[ $EXIT_CODE -eq 0 ]]; then
    curl -s -X POST "https://factory.pplayouts.trade/heartbeat/strategy-factory" \
        -H "x-api-key: ${FACTORY_API_KEY}" \
        -G --data-urlencode "success=true" > /dev/null || true
else
    curl -s -X POST "https://factory.pplayouts.trade/heartbeat/strategy-factory" \
        -H "x-api-key: ${FACTORY_API_KEY}" \
        -G --data-urlencode "success=false" > /dev/null || true
fi

exit $EXIT_CODE

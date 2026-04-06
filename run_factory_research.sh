#!/bin/bash
# Entry point for research runs — sources env and runs the research environment.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi
export FACTORY_ENV="research"

cd "$SCRIPT_DIR"
uv run python -m factory.runner
EXIT_CODE=$?

DASHBOARD_REPO="${DASHBOARD_REPO:-$HOME/workai/projects/pplayouts-dashboard}"
echo "[dashboard] publishing snapshot after research run..."
uv run python -m scripts.publish_dashboard "$DASHBOARD_REPO" --commit --push \
  --message "dashboard: auto-update after research factory run" \
  || echo "[dashboard] publish failed (non-fatal)"

# Heartbeat ping
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('research')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('research', success=False)" 2>/dev/null || true
fi

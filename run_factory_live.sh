#!/bin/bash
# Entry point for live runs — sources env and runs the live environment.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi
export FACTORY_ENV="live"

cd "$SCRIPT_DIR"
uv run python -m factory.runner
EXIT_CODE=$?

DASHBOARD_REPO="${DASHBOARD_REPO:-$HOME/workai/projects/pplayouts-dashboard}"
echo "[dashboard] publishing snapshot after live run..."
uv run python -m scripts.publish_dashboard "$DASHBOARD_REPO" --commit --push \
  --message "dashboard: auto-update after live factory run" \
  || echo "[dashboard] publish failed (non-fatal)"

# Heartbeat ping (based on main command exit code, not dashboard publish)
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('live')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('live', success=False)" 2>/dev/null || true
fi

#!/bin/bash
# Twice-daily strategy factory: evaluation + strategy generation cycle.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi

cd "$SCRIPT_DIR"
PYTHONPATH=. uv run python scripts/strategy_factory_cycle.py
EXIT_CODE=$?

DASHBOARD_REPO="${DASHBOARD_REPO:-$HOME/workai/projects/pplayouts-dashboard}"
echo "[dashboard] publishing snapshot after strategy factory cycle..."
uv run python -m scripts.publish_dashboard "$DASHBOARD_REPO" --commit --push \
  --message "dashboard: strategy factory cycle auto-update" \
  || echo "[dashboard] publish failed (non-fatal)"

# Heartbeat ping (based on main command exit code, not dashboard publish)
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('strategy-factory')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('strategy-factory', success=False)" 2>/dev/null || true
fi

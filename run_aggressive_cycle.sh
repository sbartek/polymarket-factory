#!/bin/bash
# Entry point for launchd — aggressive evaluation + strategy generation cycle.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

export PATH="/Users/barteks/.local/bin:/Users/barteks/.local/share/fnm/node-versions/v24.14.0/installation/bin:$PATH"

cd "$SCRIPT_DIR"
PYTHONPATH=. ./.venv/bin/python scripts/aggressive_strategy_cycle.py

echo "[dashboard] publishing snapshot after aggressive cycle..."
uv run python -m scripts.publish_dashboard ~/workai/projects/pplayouts-dashboard --commit --push \
  --message "dashboard: aggressive evaluation cycle auto-update" \
  || echo "[dashboard] publish failed (non-fatal)"

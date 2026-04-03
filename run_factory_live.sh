#!/bin/bash
# Entry point for launchd live runs — sources .env and runs the live environment.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

export PATH="/Users/barteks/.local/bin:/Users/barteks/.local/share/fnm/node-versions/v24.14.0/installation/bin:$PATH"
export FACTORY_ENV="live"

cd "$SCRIPT_DIR"
uv run python -m factory.runner

echo "[dashboard] publishing snapshot after live run..."
uv run python -m scripts.publish_dashboard ~/workai/projects/pplayouts-dashboard --commit --push \
  --message "dashboard: auto-update after live factory run" \
  || echo "[dashboard] publish failed (non-fatal)"

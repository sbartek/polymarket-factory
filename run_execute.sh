#!/bin/bash
# Phase 2: execute cached signals, resolve positions, send WhatsApp.
# Fast — no LLM or news calls, reads pre-cached signals from scan phase.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

export PATH="/Users/barteks/.local/bin:/Users/barteks/.local/share/fnm/node-versions/v24.14.0/installation/bin:$PATH"
export FACTORY_ENV="${FACTORY_ENV:-paper}"

cd "$SCRIPT_DIR"
uv run python -m factory.runner --phase execute

echo "[dashboard] publishing snapshot..."
uv run python -m scripts.publish_dashboard ~/workai/projects/pplayouts-dashboard --commit --push \
  --message "dashboard: auto-update after execute phase (mac)" \
  || echo "[dashboard] publish failed (non-fatal)"

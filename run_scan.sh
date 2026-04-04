#!/bin/bash
# Phase 1: scan markets and cache signals to DB.
# Run ~30min before execute phase so LLM/news calls don't block execution.

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
uv run python -m factory.scanner --limit 400

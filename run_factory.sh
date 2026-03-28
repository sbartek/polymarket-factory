#!/bin/bash
# Entry point for launchd — sources .env and runs the factory runner.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

export PATH="/Users/barteks/.local/bin:/Users/barteks/.local/share/fnm/node-versions/v24.14.0/installation/bin:$PATH"

cd "$SCRIPT_DIR"
exec uv run python -m factory.runner

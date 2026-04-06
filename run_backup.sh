#!/bin/bash
# Daily DB backup with GCS upload.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi

cd "$SCRIPT_DIR"
uv run python scripts/backup_db.py --keep 14
EXIT_CODE=$?

# Heartbeat ping
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('backup')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('backup', success=False)" 2>/dev/null || true
fi

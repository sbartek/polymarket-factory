#!/bin/bash
# Daily DB backup — pg_dump to GCS.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi

cd "$SCRIPT_DIR"

STAMP=$(date -u +%Y-%m-%d)
BACKUP_DIR="$SCRIPT_DIR/backups"
DUMP_FILE="$BACKUP_DIR/factory-${STAMP}.sql.gz"
GCS_BUCKET="pplayouts-factory-backups"

mkdir -p "$BACKUP_DIR"

# pg_dump compressed
pg_dump "$DATABASE_URL" | gzip > "$DUMP_FILE"
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]]; then
    echo "Backup created: $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"

    # Upload to GCS
    if command -v gcloud &>/dev/null; then
        gcloud storage cp "$DUMP_FILE" "gs://${GCS_BUCKET}/" && echo "Uploaded to GCS"
    fi

    # Keep only 1 local backup
    find "$BACKUP_DIR" -name 'factory-*.sql.gz' -not -name "factory-${STAMP}.sql.gz" -delete
    # Clean old SQLite backups
    find "$BACKUP_DIR" -name 'factory-*.sqlite3' -delete 2>/dev/null
fi

# Heartbeat ping
if [[ $EXIT_CODE -eq 0 ]]; then
    uv run python -c "from factory.healthcheck import ping; ping('backup')" 2>/dev/null || true
else
    uv run python -c "from factory.healthcheck import ping; ping('backup', success=False)" 2>/dev/null || true
fi

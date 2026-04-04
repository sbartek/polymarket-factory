#!/bin/bash
# CLOB trade data fetcher — fetch recent trades every 30 min.

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
uv run python -m factory.trade_fetcher --limit 5000

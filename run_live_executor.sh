#!/bin/bash
# Execute pending live orders via Polymarket CLOB.
# Runs on Mac (non-US region) — the VM enqueues orders, this script executes them.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
export PATH="/Users/barteks/local/bin:/Users/barteks/.local/bin:$PATH"

# SSH tunnel to Cloud SQL via VM (if not already running)
if ! nc -z localhost 5433 2>/dev/null; then
    ssh -f -N -L 5433:34.172.135.184:5432 gpplayouts
    sleep 1
fi

cd "$SCRIPT_DIR"
.venv/bin/python -m factory.live_executor

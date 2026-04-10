#!/bin/bash
# Run strategy factory on Mac via the Python orchestrator.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
export PATH="/Users/barteks/.local/bin:$PATH"

cd "$SCRIPT_DIR"
exec .venv/bin/python scripts/strategy_factory_local_runner.py

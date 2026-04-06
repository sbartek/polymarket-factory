#!/bin/bash
# Phase 2: execute cached signals, resolve positions, send notifications.
# Fast — no LLM or news calls, reads pre-cached signals from scan phase.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/vm_env.sh" ]]; then
    source "$SCRIPT_DIR/vm_env.sh"
else
    if [[ -f "$SCRIPT_DIR/.env" ]]; then set -a; source "$SCRIPT_DIR/.env"; set +a; fi
    export PATH="/Users/barteks/.local/bin:$PATH"
fi
export FACTORY_ENV="${FACTORY_ENV:-paper}"

cd "$SCRIPT_DIR"
uv run python -m factory.runner --phase execute
EXIT_CODE=$?

DASHBOARD_REPO="${DASHBOARD_REPO:-$HOME/workai/projects/pplayouts-dashboard}"
echo "[dashboard] publishing snapshot..."
uv run python -m scripts.publish_dashboard "$DASHBOARD_REPO" --commit --push \
  --message "dashboard: auto-update after execute phase" \
  || echo "[dashboard] publish failed (non-fatal)"

# Healthcheck ping (based on main command exit code, not dashboard publish)
PING_KEY="${HEALTHCHECKS_PING_KEY:-}"
if [[ -n "$PING_KEY" ]]; then
    if [[ $EXIT_CODE -eq 0 ]]; then
        curl -fsS -m 10 --retry 3 "https://hc-ping.com/$PING_KEY/execute" > /dev/null 2>&1 || true
    else
        curl -fsS -m 10 --retry 3 "https://hc-ping.com/$PING_KEY/execute/fail" > /dev/null 2>&1 || true
    fi
fi

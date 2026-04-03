# CR-20260403-007 — Runtime environments and separate live launchd path

**Date:** 2026-04-03
**Type:** runtime / operations
**Status:** done

## What changed

- Added explicit runtime environments in the runner: `research`, `paper`, `live`
- Added environment-policy gating so:
  - `research` logs signals only
  - `paper` opens paper trades only
  - `live` only opens explicit live-only, `live_ready` strategies
- Blocked generated strategies from live execution
- Separated broker visibility so paper brokers do not see live trades and live brokers do not see paper trades
- Added `run_factory_live.sh`
- Added `launchd/com.polymarket.factory.live.plist`
- Added `factory-live.log` to `.gitignore`

## Why

The previous structure treated live trading as a strategy-level escape hatch inside the main runner. That was too weak operationally:

- live and paper behavior were not first-class runtime concepts
- paper duplicate checks and summaries could be contaminated by live trades
- there was no separate scheduler/entrypoint for real-money execution

The new structure makes live trading a stricter environment rather than a boolean hidden inside paper mode.

## What was NOT changed

- No full launchd install/reload was performed
- No end-to-end live run was executed against external APIs
- No strategy graduation rules were changed beyond the new environment gates

## Signal to watch

- Confirm the live plist stays isolated to the intended 19:30 run
- Confirm dashboard publishing after live runs is acceptable operationally
- If more live strategies are added, move from a single live schedule to strategy-aware live scheduling

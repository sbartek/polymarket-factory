# CR-20260403-009 — Research runtime entrypoint and launchd path

**Date:** 2026-04-03
**Type:** runtime / operations
**Status:** done

## What changed

- Added `run_factory_research.sh` as a dedicated research-environment entrypoint
- Added `launchd/com.polymarket.factory.research.plist`
- Added `factory-research.log` to `.gitignore`
- Updated README command examples to include the dedicated research script

## Why

The environment split was implemented in code, but operationally only paper and live had dedicated entrypoints.
Adding a separate research path makes the three-environment model complete:

- `research` — log signals only
- `paper` — paper trades only
- `live` — real-money execution for live-only strategies

This makes research runs first-class rather than just an environment variable override on an ad hoc manual command.

## What was NOT changed

- The research launchd plist was added, but not installed into `~/Library/LaunchAgents` in this change
- No new benchmark automation was attached to research runs
- No strategy eligibility rules changed

## Signal to watch

- Decide whether the research schedule should stay once daily or become demand-driven only
- If research output becomes noisy, keep it unscheduled and retain the script for manual use only

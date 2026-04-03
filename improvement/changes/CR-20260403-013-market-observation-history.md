# CR-20260403-013 — Market observation history for benchmark labeling

**Date:** 2026-04-03
**Type:** runtime / benchmark
**Status:** done

## What changed

- Added a `market_observations` table in `factory/db.py`
- Added `FactoryDB.log_market_observations(...)` for bulk observation writes
- Updated `factory/runner.py` to persist market observations from every fetched snapshot
- Updated `scripts/build_replay_benchmark.py` to prefer `market_observations` as the forward price source before falling back to `signals` and `signal_execution_checks`
- Added focused tests in `tests/test_db.py`, `tests/test_runner_hourly_delta.py`, and `tests/test_replay_benchmark.py`

## Why

The benchmark's directional labels were improving, but still depended on the same market reappearing later in signal or execution data.
That made label coverage accidental.

Persisting the fetched market snapshot directly creates a stable price-history substrate for future replay labeling.

## What was NOT changed

- No historical backfill job was added for old runs
- No dashboard page was added yet for market observation coverage
- Existing benchmark JSON shape was not changed beyond using the new source when available

## Signal to watch

- Observation coverage only improves after new research/paper/live runs write into `market_observations`
- If the table grows quickly, add retention or aggregation before using it for longer history windows

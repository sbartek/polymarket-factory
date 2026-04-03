# CR-20260403-015 — Raw market snapshot archives for future reconstruction

**Date:** 2026-04-03
**Type:** runtime / data retention
**Status:** done

## What changed

- Added `market_snapshot_archives` in `factory/db.py`
- Updated `factory/runner.py` to persist the raw `fetch_top()` payload for each run
- Added DB coverage in `tests/test_db.py`

## Why

Derived `market_observations` are useful for benchmarking, but not enough if reconstruction needs change later.
Persisting the raw fetched snapshot means future runs keep the original market payload needed to:

- rebuild derived observation tables
- debug historical benchmark behavior
- audit what the runner actually saw

## What was NOT changed

- No backfill was performed for older runs
- No dashboard page was added for raw snapshot archives
- No compression/retention policy exists yet for the archive table

## Backfill decision

Historical backfill is not feasible from current local artifacts.
The repo only has SQLite state plus `trades.csv`, and `run_logs` do not contain full market snapshots.

So:

- older runs are not reconstructible
- future runs are now reconstructible

## Signal to watch

- Track growth of `market_snapshot_archives.payload_json`
- Add retention or compression if raw snapshot storage becomes material

# CR-20260403-008 — Dashboard benchmark visibility and reference refresh

**Date:** 2026-04-03
**Type:** dashboard / observability
**Status:** done

## What changed

- Exported replay benchmark summaries into `dashboard-data/benchmarks.json`
- Added a replay benchmark panel to the dashboard overview page
- Fixed wiki rendering so strategy names with underscores (for example `ev_news`, `stale_market`) are not italicized in the dashboard bundle
- Refreshed `dashboard/reference.html` with:
  - replay benchmark documentation
  - research / paper / live environment model
  - current launchd schedules
  - live-only `carry_rewards`
  - updated operations commands

## Why

The benchmark existed only as standalone JSON in `benchmark-data/`, which made it effectively invisible during normal operator review.

The reference page was also stale in several important places:
- old runner model
- old live semantics
- old schedule
- no benchmark documentation

Making the benchmark visible in the dashboard reduces friction for strategy review and gives the reference page a current description of how the factory actually operates.

## What was NOT changed

- No automatic strategy decisions are driven from the benchmark yet
- No new benchmark dimensions were added beyond the existing strategy-level summary
- No per-market or per-signal-family benchmark breakdown exists yet

## Signal to watch

- Once generated strategies start producing signals, verify the generated benchmark scope appears in dashboard data
- If strategy-level scoring proves too coarse, add subtype/topic breakdowns next rather than replacing the headline score

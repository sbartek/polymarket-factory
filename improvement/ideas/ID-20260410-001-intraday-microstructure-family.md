# Strategy Idea

- **idea_id:** ID-20260410-001
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** blocked

## One-line thesis

Use short-horizon order-book and spread changes to detect temporary dislocations such as liquidity withdrawal, spread blowouts, and depth refresh mean reversion.

## Why keep this around?

The thesis is plausible, but it needs a data layer the current system does not yet have. Several parked generated strategies depend on this family.

## Why not now?

- missing data: no reliable time-series snapshots of bid/ask, spread, or depth
- missing infra: no dedicated storage/query path for high-frequency market microstructure
- overlap with existing strategy: none directly, but current system is optimized for slower structural and news-based scans
- other reason: sparse or irregular snapshots would make these alerts noisy and misleading

## What would need to be true to revive it?

- best bid/ask plus size snapshots stored at fixed intervals
- at least one week of reliable data quality validation
- a clear schema for spread, depth, and staleness metrics
- one narrow first candidate, not a whole family at once

## Related files or notes

- strategy: VM-only parked generated strategies `liquidity_refresh_edge` and `intraday_liquidity_shock_reversion`
- review: 2026-04-10 discussion on generated strategy triage

## Promotion trigger

Promote this to `proposals/` only after the repo has a stable microstructure ingestion path and a first concrete candidate logic that can be validated on stored snapshots.

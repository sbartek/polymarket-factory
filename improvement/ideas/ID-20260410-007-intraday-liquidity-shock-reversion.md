# Strategy Idea

- **idea_id:** ID-20260410-007
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** blocked

## One-line thesis

Abrupt intraday price shocks caused by temporary order-book imbalance may partially revert once liquidity normalizes.

## Why keep this around?

It is a real market microstructure idea, but it is currently unsupported by the repo's data model.

## Why not now?

- missing data: no book snapshots, spread history, or high-frequency trade path
- missing infra: no time-series microstructure pipeline
- overlap with existing strategy: belongs to the same family as `liquidity_refresh_edge`
- other reason: sparse polling would confuse real shocks with missing observations

## What would need to be true to revive it?

- regular high-frequency market snapshots
- a reliable way to distinguish book shock from real information arrival
- evidence that reversion signals survive realistic polling gaps

## Related files or notes

- strategy: VM-only parked generated `intraday_liquidity_shock_reversion`
- idea: `ID-20260410-001-intraday-microstructure-family`

## Promotion trigger

Promote this to `proposals/` only after microstructure ingestion is in place and a first conservative reversion definition can be validated.

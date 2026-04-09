# Strategy Idea

- **idea_id:** ID-20260410-006
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** blocked

## One-line thesis

After temporary liquidity withdrawal or spread widening, prices may mean-revert when quoted depth returns.

## Why keep this around?

The microstructure thesis is plausible, but it depends on data the current repo does not collect.

## Why not now?

- missing data: no time-series snapshots of bid/ask, spread, or depth
- missing infra: no microstructure storage/query layer
- overlap with existing strategy: belongs to the broader intraday microstructure family
- other reason: without dense snapshots, the signal would mostly be fiction

## What would need to be true to revive it?

- reliable spread and depth snapshots at fixed intervals
- validated data quality over at least a week
- a narrow first definition of "liquidity refresh" that can be backtested

## Related files or notes

- strategy: VM-only parked generated `liquidity_refresh_edge`
- idea: `ID-20260410-001-intraday-microstructure-family`

## Promotion trigger

Promote this to `proposals/` only after microstructure data collection exists and a concrete refresh metric can be measured on stored snapshots.

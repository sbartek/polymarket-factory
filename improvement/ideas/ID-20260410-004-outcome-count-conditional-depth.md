# Strategy Idea

- **idea_id:** ID-20260410-004
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** backlog

## One-line thesis

Conditional markets with many count-style outcome buckets can develop probability distortions that are more visible in the distribution shape than in any single leg.

## Why keep this around?

This is close to the newly rescued `conditional_outcome_count_asymmetry` logic and could become a stronger second-generation version rather than a separate strategy.

## Why not now?

- missing data: none beyond current market metadata
- missing infra: better bucket parsing and cluster normalization would help
- overlap with existing strategy: heavily overlaps with `conditional_outcome_count_asymmetry`
- other reason: should probably become a refinement or submode of that strategy, not a separate registry entry

## What would need to be true to revive it?

- clear evidence that distribution-shape checks add signal quality beyond simple oversum checks
- robust parsing for count ranges and bucket adjacency
- a design that avoids duplicating alerts from the current rescued strategy

## Related files or notes

- strategy: VM-only parked generated `outcome_count_conditional_depth`
- strategy: `conditional_outcome_count_asymmetry`

## Promotion trigger

Promote this to `proposals/` only if it is defined as a concrete refinement of the existing conditional count strategy rather than a redundant sibling.

# Strategy Idea

- **idea_id:** ID-20260410-002
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** backlog

## One-line thesis

If several conditional child markets imply inconsistent probabilities relative to the same parent condition, the mismatch can expose a structural pricing cascade.

## Why keep this around?

This is a plausible extension of the conditional family and overlaps with the same market structure that made `conditional_outcome_count_asymmetry` worth rescuing.

## Why not now?

- missing data: none strictly required beyond current market metadata, but parent-child mapping is still heuristic
- missing infra: stronger conditional graph extraction would help a lot
- overlap with existing strategy: partially overlaps with `conditional_outcome_count_asymmetry` and `conditional_probability_mispricing`
- other reason: should be designed as part of a broader conditional framework, not as another isolated thin strategy

## What would need to be true to revive it?

- a more reliable conditional market grouping layer
- a clear definition of which inconsistencies are distinct from existing conditional strategies
- backtests showing incremental alert value over the current conditional set

## Related files or notes

- strategy: VM-only parked generated `conditional_mispricing_cascade`
- strategy: `conditional_outcome_count_asymmetry`
- strategy: `conditional_probability_mispricing`

## Promotion trigger

Promote this to `proposals/` only if it can be framed as a distinct conditional inconsistency detector rather than a duplicate of the current conditional strategies.

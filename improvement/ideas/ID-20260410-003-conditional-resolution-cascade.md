# Strategy Idea

- **idea_id:** ID-20260410-003
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** backlog

## One-line thesis

When one market in a linked conditional cluster is effectively resolved in practice, sibling markets may lag in repricing and expose alertable resolution cascades.

## Why keep this around?

The thesis is coherent and could fit well with the system's existing interest in slow-to-resolve or structurally linked markets.

## Why not now?

- missing data: robust resolution-state evidence for related markets is still thin
- missing infra: better parent-child and sibling linkage logic is needed
- overlap with existing strategy: overlaps with `resolution_hunter_v2` and the broader conditional family
- other reason: likely better as a hybrid of conditional structure plus resolution detection than as a standalone generated strategy

## What would need to be true to revive it?

- reliable linkage between sibling conditional markets
- a conservative definition of "effectively resolved" before official settlement
- evidence that the lag is not already captured by `resolution_hunter_v2`

## Related files or notes

- strategy: VM-only parked generated `conditional_resolution_cascade`
- strategy: `resolution_hunter_v2`

## Promotion trigger

Promote this to `proposals/` only after the conditional linkage model is stronger and the edge can be shown as distinct from generic near-resolution scanning.

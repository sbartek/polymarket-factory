# PPLayouts Improvement Ledger

This directory is the practical implementation of the improvement harness described in:
- `PPLAYOUTS_IMPROVEMENT_HARNESS.md`

Its job is simple:
- remember what changed
- remember why it changed
- record how it was validated
- keep experiments and conclusions attributable

## Structure

- `changes/` — one record per meaningful change
- `experiments/` — one record per experiment / validation window
- `ideas/` — parked strategy concepts worth keeping, but not ready to implement
- `metrics/` — metric definitions with maturity and caveats
- `proposals/` — concrete candidate strategies under active review
- `reviews/` — reviewer notes and verdict summaries
- `templates/` — templates for the above records

## Rules

- Production is the source of truth for live behavior.
- This directory is the source of truth for *improvement memory*.
- Do not silently change success criteria after seeing results.
- Prefer one clear experiment over five muddy ones.
- Keep records short, concrete, and linked to commits when possible.

## Current status

Initial scaffolding and first real records were added on 2026-03-31 after the major PPLayouts refactor that introduced:
- SQLite-backed state
- run/decision logging
- time-window taxonomy
- new strategy/portfolio operator tooling

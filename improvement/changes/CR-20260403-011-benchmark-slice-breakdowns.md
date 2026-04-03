# CR-20260403-011 — Replay benchmark slice breakdowns in dashboard

**Date:** 2026-04-03
**Type:** benchmark / dashboard
**Status:** done

## What changed

- Extended `scripts/build_replay_benchmark.py` to emit `strategy_slices` grouped by `strategy`, `edge_type`, and `time_window`
- Added slice-level regression coverage in `tests/test_replay_benchmark.py`
- Added a new Benchmark slices panel to `dashboard/strategies.html`
- Rebuilt the benchmark artifacts, dashboard snapshot, and static bundle

## Why

The strategy-level replay benchmark was enough for keep/archive gating, but too coarse for diagnosis.
This change makes it possible to see whether a strategy is weak overall or only weak in one subtype.

The dashboard can now answer questions like:

- which `edge_type` slice is actually carrying a strategy
- whether a bad score is localized to one `time_window`
- whether a generated strategy has one promising slice worth preserving

## What was NOT changed

- No new label source or outcome labeling logic was added
- No per-market detail page was added
- The current dashboard view is still table-based and not a full drill-down workflow

## Signal to watch

- If strategies begin producing multiple meaningful slice rows, add links from strategy rows into prefiltered slice views
- If slice counts remain sparse, add minimum-sample highlighting so weak slices are not overread

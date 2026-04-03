# CR-20260403-014 — Coverage-aware generated strategy retention

**Date:** 2026-04-03
**Type:** autonomous loop / benchmark policy
**Status:** done

## What changed

- Updated `scripts/aggressive_strategy_cycle.py` so generated strategies are only archived for weak benchmark scores when benchmark evidence is also sufficient
- Added observation-based thresholds alongside the existing signal/labeled thresholds
- Low-score generated strategies with thin evidence now remain `pending_benchmark_review` instead of being archived immediately
- Added regression coverage in `tests/test_aggressive_strategy_cycle.py`

## Why

The benchmark and dashboard were already showing evidence quality, but the retention gate still behaved too much like a score-only rule.
That could over-prune generated strategies on small or weakly observed samples.

The retention loop now aligns with the benchmark coverage model:

- weak score + enough evidence → archive
- weak score + thin evidence → keep pending review

## What was NOT changed

- No new benchmark score formula was added
- No generated strategy was auto-promoted
- No dashboard workflow changed beyond the previously added coverage visibility

## Signal to watch

- If too many generated strategies remain stuck in `pending_benchmark_review`, observation coverage may be too sparse and a backfill/history policy will matter more
- If almost nothing gets archived anymore, revisit the observed-signal or observation-coverage thresholds rather than dropping back to score-only gating

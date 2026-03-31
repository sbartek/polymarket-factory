# Change Record

- **change_id:** CR-20260331-004
- **date:** 2026-03-31
- **author:** Leon (agent)
- **component:** correlated_pairs strategy evaluation workflow
- **owner:** Bartek
- **risk_tier:** Tier 1
- **decision_class:** C
- **status:** running

## Summary

Start a disciplined evaluation thread for the `correlated_pairs` MVP instead of treating it as just another new strategy file.

## Hypothesis

A narrow, explicitly reviewed logical-inconsistency strategy can become a viable medium-window edge class if pair quality and relationship validity are tracked carefully.

## Expected impact

- target metric(s): candidate-pair quality, signal validity, skip/open pattern clarity
- expected direction: improve understanding before changing logic further

## Validation path

- paper / review
- use detail tables, run analytics, and `/details corr`

## Evidence

- commit(s): `d68df52`, `057ad85`, `f024df6`
- script/report: `scripts/strategy_checks.py correlated_pairs`, `scripts/run_analytics.py`, `/details corr`
- experiment record(s): `EX-20260331-004`

## Verdict

- collect more data

## Notes

This is intentionally an evaluation-first record, not a claim that the strategy already works.

# Experiment Record

- **experiment_id:** EX-20260331-005
- **date:** 2026-03-31
- **related_change_id:** CR-20260331-005
- **component:** stale_market MVP
- **owner:** Bartek
- **status:** planned

## Hypothesis

`stale_market` can become a more practical delayed-information strategy than `ev_news` if recent candidates show coherent topic mapping, sensible opens, and acceptable skip/open ratios over a short run window.

## Validation window / method

- dataset or live window: next 5–10 runs
- replay / paper / staging / review: paper / dry + detail-table review

## Metrics

- primary:
  - candidate count per run
  - opens per run
  - topic concentration among recent checks
- secondary:
  - top skip reasons connected to `stale_market`
  - closed trades as they accumulate
  - exposure growth versus current caps
- metric maturity: experimental

## Before / after / observations

- before: `stale_market` looked promising operationally but did not yet have an explicit experiment thread
- after: evaluation will use persisted `stale_market_checks`, open-book inspection, and recent decision patterns
- observations: recent runs suggest `stale_market` is one of the most operationally active strategies in the current stack

## Verdict

- collect more data
- confidence: low

## Notes

If topic concentration becomes too narrow or skip reasons suggest low-quality candidates, tighten filters before raising conviction.

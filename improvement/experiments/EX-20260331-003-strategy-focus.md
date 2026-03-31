# Experiment Record

- **experiment_id:** EX-20260331-003
- **date:** 2026-03-31
- **related_change_id:** CR-20260331-003
- **component:** strategy portfolio focus
- **owner:** Bartek
- **status:** complete

## Hypothesis

Pausing obvious losers and focusing on more coherent edge classes would improve the research portfolio and reduce noise.

## Validation window / method

- dataset or live window: same-day strategy review and dry-run validation
- replay / paper / staging / review: trade-history review + paper-run behavior checks

## Metrics

- primary: cleaner active-vs-legacy split, reduced noisy strategy output, more coherent operator summaries
- secondary: current open-book composition, recent opener distribution by strategy
- metric maturity: experimental

## Before / after / observations

- before: active/legacy lines were muddled, and poor strategies were still part of the main stack
- after: paused strategies are clearly legacy; active strategy set is smaller and cleaner; tooling reflects the split
- observations: `stale_market` is currently the most active opener; `correlated_pairs` is still too early to judge

## Verdict

- keep direction, collect more data
- confidence: medium

## Notes

Good strategic cleanup, but still not enough closed-trade data to declare winners among the new/retained strategies.

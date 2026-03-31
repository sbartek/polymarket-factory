# Experiment Record

- **experiment_id:** EX-20260331-004
- **date:** 2026-03-31
- **related_change_id:** CR-20260331-004
- **component:** correlated_pairs MVP
- **owner:** Bartek
- **status:** planned

## Hypothesis

`correlated_pairs` can surface useful logical inconsistencies if the relationship mapping is constrained and the output is reviewed through persisted pair-check data instead of intuition alone.

## Validation window / method

- dataset or live window: next 5–10 runs
- replay / paper / staging / review: paper / dry + detail-table review

## Metrics

- primary:
  - candidate pairs per run
  - LLM-hit rate from candidate pairs
  - opens generated
- secondary:
  - top relationship classes surfaced
  - skip reasons for resulting signals
  - any realized closed trades if available
- metric maturity: experimental

## Before / after / observations

- before: no structured evaluation thread existed for `correlated_pairs`
- after: use persisted `correlated_pairs_checks` rows plus decision logs for evaluation
- observations: current evidence is too thin; this record exists to prevent premature storytelling

## Verdict

- collect more data
- confidence: low

## Notes

If pair quality remains poor after a modest sample window, narrow templates further before expanding the strategy.

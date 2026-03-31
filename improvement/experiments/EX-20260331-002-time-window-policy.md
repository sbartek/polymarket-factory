# Experiment Record

- **experiment_id:** EX-20260331-002
- **date:** 2026-03-31
- **related_change_id:** CR-20260331-002
- **component:** time-window taxonomy and policy
- **owner:** Bartek
- **status:** complete

## Hypothesis

Time-window-aware scheduling and exposure caps would make portfolio behavior easier to interpret and operate.

## Validation window / method

- dataset or live window: same-day dry/live smoke validation
- replay / paper / staging / review: dry runs + live lock smoke test + output inspection

## Metrics

- primary: runner executes with expected skip/cadence behavior, reports group cleanly by time window
- secondary: operator readability in `/details` and CLI scripts
- metric maturity: usable

## Before / after / observations

- before: strategies were mostly a flat list
- after: reports, summaries, and operator tooling reflect `super_short` / `short` / `medium` and active vs legacy context
- observations: taxonomy is operationally useful; long-term declared-vs-realized hold behavior still needs review

## Verdict

- keep
- confidence: medium

## Notes

This should later be paired with a review note on declared vs realized hold duration.

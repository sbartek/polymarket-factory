# Change Record

- **change_id:** CR-20260331-002
- **date:** 2026-03-31
- **author:** Leon (agent)
- **component:** strategy taxonomy / runner policy / portfolio reporting
- **owner:** Bartek
- **risk_tier:** Tier 2
- **decision_class:** C
- **status:** accepted

## Summary

Added first-class strategy metadata for edge type and time window, including `super_short`, and made time windows operational in scheduling, exposure caps, and reporting.

## Hypothesis

Explicit time windows would make the portfolio more interpretable and allow cadence/exposure policy to reflect actual strategy behavior instead of treating all strategies the same.

## Expected impact

- target metric(s): interpretability, policy clarity, portfolio risk hygiene
- expected direction: improve

## Validation path

- code inspection
- dry-run validation
- reporting review

## Evidence

- commit(s): `d68df52`
- script/report: `eval/report.py`, `scripts/open_positions.py`, `/details portfolio`
- experiment record(s): `EX-20260331-002`

## Verdict

- keep

## Notes

Time-window usefulness is still partly conceptual; declared vs realized behavior should be reviewed later.

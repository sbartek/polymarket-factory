# Change Record

- **change_id:** CR-20260331-003
- **date:** 2026-03-31
- **author:** Leon (agent)
- **component:** strategy set / portfolio hygiene
- **owner:** Bartek
- **risk_tier:** Tier 2
- **decision_class:** D
- **status:** accepted

## Summary

Paused `fade_certainty` and `weather_edge`, tightened `spread_arb`, added `stale_market`, and added `correlated_pairs` MVP.

## Hypothesis

Reducing obviously losing/noisy strategies and focusing on cleaner edge classes would improve the research portfolio and reduce misleading activity.

## Expected impact

- target metric(s): signal quality, portfolio coherence, research learning speed
- expected direction: improve

## Validation path

- paper-trade review
- strategy code review
- dry-run validation

## Evidence

- commit(s): `d68df52`
- script/report: `docs/strategy_review_2026-03-31.md`, `docs/implementation_plan_2026-03-31.md`, `/details legacy`
- experiment record(s): `EX-20260331-003`

## Verdict

- keep current direction

## Notes

`correlated_pairs` remains MVP-level and needs more empirical validation.

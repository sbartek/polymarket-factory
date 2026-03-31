# Review Note

- **review_id:** RV-20260331-001
- **date:** 2026-03-31
- **component:** PPLayouts system state after major refactor
- **reviewer:** Leon (agent)
- **related_change_ids:** CR-20260331-001, CR-20260331-002, CR-20260331-003
- **related_experiment_ids:** EX-20260331-001, EX-20260331-002, EX-20260331-003

## What looks solid

- SQLite migration materially improved durability and observability.
- Operator tooling is now meaningfully useful (`/details`, latest-run queries, open/legacy/run analytics).
- Active vs legacy split made the portfolio easier to interpret.

## What is still uncertain

- `correlated_pairs` is too early to judge.
- `stale_market` looks operationally alive, but still needs more closed-trade evidence.
- Time-window categories are useful operationally, but declared vs realized hold behavior still needs review.

## Recommendation

- keep
- continue with controlled experimentation rather than broad feature sprawl

## Next measurements needed

- realized outcomes for new active strategies
- declared vs realized hold-time review by time window
- skip-reason patterns by strategy over a larger live sample

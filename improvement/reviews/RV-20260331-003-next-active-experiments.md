# Review Note

- **review_id:** RV-20260331-003
- **date:** 2026-03-31
- **component:** next active experiment threads
- **reviewer:** Leon (agent)
- **related_change_ids:** CR-20260331-004, CR-20260331-005
- **related_experiment_ids:** EX-20260331-004, EX-20260331-005

## What looks solid

- `correlated_pairs` and `stale_market` now both have explicit forward-looking evaluation records.
- This reduces the risk of strategy conclusions being formed from scattered tooling output without a declared evaluation thread.

## What is still uncertain

- `correlated_pairs` may remain too semantically loose.
- `stale_market` may be operationally active without yet being economically strong.

## Recommendation

- collect more data
- review both threads after 5–10 runs before material logic changes

## Next measurements needed

- pair quality vs opens for `correlated_pairs`
- candidate quality / topic concentration / opens for `stale_market`

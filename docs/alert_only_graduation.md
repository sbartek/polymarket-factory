# Alert-Only Graduation

`correlated_laggard` and `esport48` are intentionally still alert-only.

The code path for future promotion is explicit:
- `trading_enabled`: runner gate for opening paper positions
- `promotable`: strategy is a valid promotion candidate once evidence is good enough
- `live_ready`: reserved for the later real-money path; keep `False` until that operational review exists

## Promotion Criteria

Promote an alert-only strategy from alerts to paper trading only after all of the following are true:

1. At least 10 live runs have been reviewed with persisted detail-table evidence.
2. At least 15 alerts or 30 candidate checks have been inspected, so the sample is not anecdotal.
3. The top alerts look directionally sensible on manual replay, with no repeated duplicate/cluster spam.
4. Liquidity and fillability look plausible for the intended size; the idea is not relying on obviously dead books.
5. Logged reasons are good enough to explain why the alert fired and why weaker candidates were skipped.
6. The strategy has an initial paper cap small enough to fail safely on first promotion.

## Promotion Workflow

1. Keep `trading_enabled = False` while the paper-eval checklist is open.
2. Mark the strategy record/review with a clear keep/promote decision.
3. Flip `trading_enabled = True` only after the checklist is complete.
4. Leave `live_ready = False` until a separate live-broker checklist exists.

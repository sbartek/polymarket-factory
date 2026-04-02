# Experiment Record

- **experiment_id:** EX-20260401-007
- **date:** 2026-04-01
- **related_change_id:** 
- **component:** esport48 paper-eval checklist
- **owner:** Bartek
- **status:** active

## Hypothesis

`esport48` can eventually graduate from alert-only if its near-expiry esport alerts are liquid enough, not just noisy favorites/underdogs, and the subtype tags help separate signal from churn.

## Validation window / method

- dataset or live window: next 10+ live runs
- replay / paper / staging / review: alert log review + detail-table review + manual paper replay

## Checklist

- [ ] Review at least 10 runs using `esport48_checks`.
- [ ] Inspect at least 15 fired alerts and 30 total candidate rows.
- [ ] Confirm the strategy is mostly finding real esport books rather than generic gaming-tag noise.
- [ ] Check whether `news/roster_edge`, `form/momentum_edge`, and `overreaction/underreaction_edge` tags are actually informative.
- [ ] Confirm alerted books have enough liquidity/volume for a small paper size.
- [ ] Check whether edge quality degrades badly inside the final 6 to 12 hours before expiry.
- [ ] Verify the first promotion can stay on a small cap before changing `trading_enabled`.

## Metrics

- primary:
  - alerts per run
  - subtype hit-rate by manual replay
  - liquidity at alert time
- secondary:
  - hours-to-close distribution
  - favorite vs underdog split
  - skipped-candidate reason mix
- metric maturity: experimental

## Notes

Do not promote just because the alerts look intuitively sharp. This strategy needs evidence that the screener is surfacing executable mispricings, not last-minute esport chaos.

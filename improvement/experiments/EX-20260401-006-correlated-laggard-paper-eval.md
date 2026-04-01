# Experiment Record

- **experiment_id:** EX-20260401-006
- **date:** 2026-04-01
- **related_change_id:** 
- **component:** correlated_laggard paper-eval checklist
- **owner:** Bartek
- **status:** planned

## Hypothesis

`correlated_laggard` can eventually graduate from alert-only if repeated leader/laggard gaps are real, non-duplicative, and paper-executable rather than just interesting.

## Validation window / method

- dataset or live window: next 10+ live runs
- replay / paper / staging / review: alert log review + detail-table review + manual paper replay

## Checklist

- [ ] Review at least 10 runs using `correlated_laggard_checks`.
- [ ] Inspect at least 15 fired alerts and 30 total checks.
- [ ] Confirm topic clustering is not mostly duplicate Trump/Fed variants from the same narrative burst.
- [ ] Confirm leader really is the more liquid market in the alerts that matter.
- [ ] Confirm divergence still looks actionable after considering spread/liquidity, not just headline price gaps.
- [ ] Check whether laggards eventually converge in the expected direction often enough to justify paper entries.
- [ ] Verify a small first-promotion cap is appropriate before changing `trading_enabled`.

## Metrics

- primary:
  - alerts per run
  - share of alerts with plausible eventual convergence
  - duplicate / same-topic concentration rate
- secondary:
  - leader volume ratio distribution
  - divergence distribution
  - skipped-candidate reason mix
- metric maturity: experimental

## Notes

Do not promote on one or two pretty divergences. This strategy only graduates if the logged sample looks repeatable across multiple topics and runs.

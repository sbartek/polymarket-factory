# Change Record

- **change_id:** CR-20260331-001
- **date:** 2026-03-31
- **author:** Leon (agent)
- **component:** storage / runtime observability
- **owner:** Bartek
- **risk_tier:** Tier 2
- **decision_class:** C
- **status:** accepted

## Summary

Migrated PPLayouts from CSV-dominant runtime state toward SQLite-backed state, first for runs/signals/decisions/logs and then for trades.

## Hypothesis

SQLite would reduce race-condition risk, improve auditability, and make future reporting/analysis materially easier.

## Expected impact

- target metric(s): runtime state safety, observability, reporting queryability
- expected direction: improve

## Validation path

- code migration
- paper/dry runs
- broker/report smoke validation

## Evidence

- commit(s): `d68df52`, `f35b5a4`
- script/report: `eval/report.py`, `scripts/latest_run.py`, `scripts/inspect_decisions.py`
- experiment record(s): `EX-20260331-001`

## Verdict

- keep

## Notes

CSV remains as compatibility/export during transition, but SQLite is now the source of truth for trade state.

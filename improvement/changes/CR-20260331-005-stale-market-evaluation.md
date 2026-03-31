# Change Record

- **change_id:** CR-20260331-005
- **date:** 2026-03-31
- **author:** Leon (agent)
- **component:** stale_market strategy evaluation workflow
- **owner:** Bartek
- **risk_tier:** Tier 1
- **decision_class:** C
- **status:** running

## Summary

Start a disciplined evaluation thread for the `stale_market` MVP using persisted check data, open-position inspection, and decision logs.

## Hypothesis

`stale_market` may be a stronger practical edge class than generic `ev_news` if candidate quality and topic concentration are reviewed through persisted checks and recent decision outcomes.

## Expected impact

- target metric(s): candidate quality, opens generated, skip patterns, eventual closed-trade usefulness
- expected direction: improve understanding before changing logic further

## Validation path

- paper / review
- use `stale_market_checks`, `run_analytics.py`, `open_positions.py`, and `/details stale`

## Evidence

- commit(s): `d68df52`, `4936492`, `057ad85`, `4ec136d`
- script/report: `scripts/strategy_checks.py stale_market`, `scripts/run_analytics.py`, `/details stale`
- experiment record(s): `EX-20260331-005`

## Verdict

- collect more data

## Notes

`stale_market` is currently the most frequent opener among active strategies in recent runs, which makes it a good candidate for the next explicit evaluation thread.

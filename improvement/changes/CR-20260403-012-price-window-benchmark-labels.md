# CR-20260403-012 — Price-window directional labels for replay benchmark

**Date:** 2026-04-03
**Type:** benchmark / evaluation
**Status:** done

## What changed

- Extended `scripts/build_replay_benchmark.py` to derive directional labels from later observed market prices on the same `market_id`
- The benchmark now uses future observations already captured in `signals` and `signal_execution_checks`
- Label windows are based on each strategy's configured hold window from `factory/strategy_meta.py`
- Added regression coverage in `tests/test_replay_benchmark.py`
- Rebuilt benchmark artifacts and dashboard data

## Why

The replay benchmark structure was in place, but most alert-only strategies had no directional labels unless a market later resolved in a recorded trade.
That made directional score too neutral to be useful.

Price-window labels make the benchmark more informative now, without waiting for a larger corpus of fully resolved trades or adding a new market-history ingestion layer.

## What was NOT changed

- No new market-history table was added to SQLite
- No separate persistent label table was added
- No live or paper execution logic changed

## Signal to watch

- Current price-window labels depend on later observations already present in the DB, so sparse follow-up coverage will still limit some strategies
- If label coverage remains patchy, the next step is a dedicated market-observation history table rather than more benchmark-side heuristics

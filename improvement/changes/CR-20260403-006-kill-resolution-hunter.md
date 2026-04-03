# CR-20260403-006 — Kill resolution_hunter

**Date:** 2026-04-03
**Type:** strategy kill
**Status:** done

## What changed

- `resolution_hunter`: `paused = True`, `trading_enabled = False`, `scan_frequency = "paused"`
- `STRATEGY_EXPOSURE_CAPS["resolution_hunter"]` → `0.0`
- Removed from `ACTIVE_STRATEGIES`

## Why

12 closed trades, -92.3% ROI, 8.3% win rate. Verdict is conclusive — this is not bad luck, it's a broken hypothesis.

Root cause hypothesis: the strategy bets that Claude can identify markets that have already resolved but aren't priced at 0/1 yet. In practice, Polymarket prices these accurately within hours of resolution. By the time we scan and signal, the edge is gone or the market is already settling. Claude confidence ≥ 85% didn't correlate with actual outcomes.

## What was NOT changed

- 1 remaining open position ($4.50) left to resolve naturally — not worth force-closing
- Strategy code preserved for reference; can be revisited with a fundamentally different approach (e.g., checking oracle data directly rather than Claude news inference)

## Signal to watch

If a future strategy revisits this edge, it needs a real-time oracle data source, not LLM news inference. The gap-to-resolution window is too short for our scan frequency.

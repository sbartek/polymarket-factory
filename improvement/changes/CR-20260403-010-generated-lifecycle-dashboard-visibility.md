# CR-20260403-010 — Generated strategy lifecycle visibility in dashboard

**Date:** 2026-04-03
**Type:** dashboard / observability
**Status:** done

## What changed

- Extended `scripts/export_dashboard_data.py` to export generated-strategy lifecycle metadata into `dashboard-data/strategies.json`
- Added generated strategy visibility to `dashboard/index.html` and `dashboard/strategies.html`
- Added an origin filter plus generated benchmark score/lifecycle columns on the Strategies page
- Included archived generated strategies in the exported strategy snapshot when present in `factory/strategies/generated/archive/`
- Added coverage in `tests/test_export_dashboard_data.py`

## Why

Benchmark-gated retention was already implemented in the aggressive cycle, but the dashboard still treated generated strategies like opaque normal rows.
That made archive decisions hard to audit from the operator view.

The dashboard now surfaces:

- whether a strategy is generated
- its lifecycle state
- its module/proposal provenance
- generated benchmark score and label count when available
- archive notes when a generated strategy was removed by the benchmark gate

## What was NOT changed

- No new benchmark scoring logic was added
- No dashboard page was added specifically for archive history
- Generated strategies without replay evidence still show no benchmark score

## Signal to watch

- If generated strategy counts grow, consider splitting lifecycle history into a dedicated page instead of mixing active and archived rows into the main strategy table
- If archive reasons become verbose, store a shorter structured archive code alongside the current human-readable note

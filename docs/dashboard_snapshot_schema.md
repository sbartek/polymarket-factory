# Dashboard Snapshot Schema

## Purpose

This document defines the first dashboard snapshot contract for PPLayouts.

The snapshot is intended to:
- be generated on the PPLayouts machine
- provide a stable JSON interface for a static external dashboard
- combine operational data from SQLite with lightweight experimentation metadata from `improvement/`
- make data freshness and warning state explicit

This schema is intentionally conservative.
It is designed for a reduced MVP, not maximum completeness.

## Snapshot design principles

- Keep the first schema small.
- Prefer explicit field names over clever nesting.
- Keep active and legacy metrics separated where interpretation differs.
- Every file should be valid and useful on its own.
- Every snapshot should advertise its age and warning state.

## Output directory

Recommended output directory:
- `dashboard-data/`

## MVP files

Required:
- `dashboard-data/manifest.json`
- `dashboard-data/overview.json`
- `dashboard-data/strategies.json`
- `dashboard-data/runs.json`
- `dashboard-data/experiments.json`

Optional for MVP:
- `dashboard-data/positions-open.json`

Deferred until after MVP:
- closed positions detail
- reviews detail
- archive/legacy detail pages
- deep decisions drill-down

---

# 1. `manifest.json`

## Purpose

Global metadata about the snapshot build.

## Required fields

```json
{
  "generated_at": "2026-04-01T18:00:00Z",
  "export_version": "v1",
  "git_commit": "abc1234",
  "warning_count": 2,
  "warnings": [
    "Paused strategies are currently grouped under legacy.",
    "Open positions snapshot excludes records with unknown status."
  ],
  "source_summary": {
    "sqlite_available": true,
    "improvement_records_available": true
  }
}
```

## Notes

- `generated_at` must always be present.
- `warning_count` should match the length of `warnings`.
- `git_commit` may be null if unavailable, but should be included.
- `source_summary` gives quick visibility into source health.

---

# 2. `overview.json`

## Purpose

Compact top-level state for the landing page.

## Required fields

```json
{
  "generated_at": "2026-04-01T18:00:00Z",
  "latest_run_status": "ok",
  "latest_run_started_at": "2026-04-01T17:45:00Z",
  "latest_run_duration_seconds": 82,
  "open_exposure_active": 1234.56,
  "open_position_count_active": 11,
  "open_exposure_legacy": 345.67,
  "open_position_count_legacy": 4,
  "active_strategy_count": 5,
  "active_experiment_count": 2,
  "execution_checks_30d": 96,
  "strategies_with_execution_checks_30d": 4,
  "avg_ev_after_slippage_50_pp_30d": 3.2,
  "avg_max_size_positive_ev_30d": 41.7,
  "execution_source_confidence_counts_30d": {
    "medium": 38,
    "low": 44,
    "very_low": 14
  },
  "alerts": [
    {
      "level": "warning",
      "message": "Latest run completed with elevated skips in correlated_pairs."
    }
  ]
}
```

## Field notes

- `latest_run_status` must use normalized status values from metric definitions.
- `alerts` should be compact and operationally meaningful.
- Do not add decorative summary prose here.

---

# 3. `strategies.json`

## Purpose

Strategy summary table for dashboard comparison.

## Structure

Top-level array of strategy summary objects.

## Example

```json
[
  {
    "strategy_name": "spread_arb",
    "status": "active",
    "open_exposure": 420.0,
    "open_positions": 3,
    "recent_signals_count": 8,
    "recent_decisions_count": 21,
    "realized_pnl_30d": 12.5,
    "realized_pnl_all_time": 31.0,
    "by_time_window": {
      "super_short": {
        "open_positions": 1,
        "open_exposure": 100.0
      },
      "intraday": {
        "open_positions": 2,
        "open_exposure": 320.0
      }
    },
    "by_edge_type": {
      "structural": {
        "open_positions": 3,
        "open_exposure": 420.0
      }
    },
    "warnings": []
  }
]
```

## Required fields per object

- `strategy_name`
- `status`
- `open_exposure`
- `open_positions`
- `recent_signals_count`
- `recent_decisions_count`
- `realized_pnl_30d`
- `realized_pnl_all_time`
- `execution_checks_count_30d`
- `avg_ev_after_slippage_10_pp_30d`
- `avg_ev_after_slippage_50_pp_30d`
- `avg_ev_after_slippage_100_pp_30d`
- `avg_max_size_positive_ev_30d`
- `avg_max_size_above_min_edge_30d`
- `execution_source_confidence_counts_30d`
- `by_time_window`
- `by_edge_type`
- `warnings`

## Notes

- `warnings` should be strategy-specific interpretation notes.
- If a strategy lacks enough data for a metric, use `null` or `unknown` semantics rather than fake values.
- Execution fields are Phase A **fill proxies**, not live fills.
- Use canonical strategy names only.

---

# 4. `runs.json`

## Purpose

Recent run-history table for system health monitoring.

## Structure

Top-level array of recent run objects, sorted newest first.

## Example

```json
[
  {
    "run_id": "run_20260401_174500",
    "started_at": "2026-04-01T17:45:00Z",
    "duration_seconds": 82,
    "status": "ok",
    "strategies_checked": 5,
    "signals_generated": 2,
    "decisions_logged": 17,
    "errors_count": 0,
    "summary": "Completed successfully with normal strategy participation."
  }
]
```

## Required fields per object

- `run_id`
- `started_at`
- `duration_seconds`
- `status`
- `strategies_checked`
- `signals_generated`
- `decisions_logged`
- `errors_count`
- `summary`

## Notes

- Keep `summary` concise and operational.
- If a field cannot be computed reliably, prefer `null` plus warning in manifest over fabricated data.

---

# 5. `experiments.json`

## Purpose

Lightweight experimentation view for MVP.

## Structure

Top-level array of experiment summary objects.

## Example

```json
[
  {
    "experiment_id": "EX-20260331-004",
    "title": "correlated_pairs mvp",
    "scope_type": "strategy",
    "scope_label": "correlated_pairs",
    "strategy": "correlated_pairs",
    "status": "active",
    "hypothesis": "Correlated market pairs can produce tradable dislocations with cleaner structure than ad hoc news chasing.",
    "linked_changes": ["CR-20260331-004"],
    "linked_reviews": ["RV-20260331-004"],
    "review_due": "2026-04-05",
    "last_updated": "2026-03-31",
    "summary": "Forward-looking evaluation thread for correlated_pairs MVP."
  }
]
```

## Required fields per object

- `experiment_id`
- `title`
- `scope_type`
- `scope_label`
- `strategy`
- `status`
- `hypothesis`
- `linked_changes`
- `linked_reviews`
- `review_due`
- `last_updated`
- `summary`

## Notes

- This is intentionally summary-level for MVP.
- Detailed review/change content can be added later.
- `review_due` may be null.

---

# 6. Optional `positions-open.json`

## Purpose

Detailed open-position page for active and paused/legacy open positions.

## Example schema

```json
[
  {
    "position_id": "trade_123",
    "strategy": "spread_arb",
    "strategy_status": "active",
    "status": "open",
    "market": "Example market title",
    "side": "yes",
    "size": 50.0,
    "entry_time": "2026-04-01T14:20:00Z",
    "time_window": "intraday",
    "edge_type": "structural",
    "lifecycle_group": "active",
    "exposure": 50.0,
    "url": "https://example.com/market",
    "warnings": []
  }
]
```

## Required fields if used

- `position_id`
- `strategy`
- `strategy_status`
- `status`
- `market`
- `side`
- `size`
- `entry_time`
- `time_window`
- `edge_type`
- `lifecycle_group`
- `exposure`
- `url`
- `warnings`

## Notes

- This file should only include currently open positions.
- `strategy_status` should use the same normalized classification as `strategies.json` (`active`, `paused`, `legacy`).
- `lifecycle_group` may remain source-derived and is allowed to differ from `strategy_status`.

---

# File-level rules

## Rule 1 — Every file must include enough information to stand alone
At minimum:
- each top-level file should either include `generated_at` itself or rely on manifest with a clearly documented convention

Recommended MVP approach:
- include `generated_at` in object-based files like `overview.json`
- array files may rely on manifest if that keeps them clean, but including file-level metadata wrappers later may be preferable

## Rule 2 — Prefer normalized values
Use canonical labels for:
- strategy names
- statuses
- time windows
- edge types
- experiment IDs

## Rule 3 — Nulls over fake certainty
If a value is not known:
- use `null`
- use `unknown` for enum-like statuses
- surface warnings where interpretation matters

## Rule 4 — Warnings are part of the product
Warnings are not noise.
They are how the snapshot tells the truth when the model is imperfect.

---

# Data freshness policy hooks

The schema should support future freshness labeling in the UI.

At minimum the dashboard should be able to compute:
- current age of snapshot from `manifest.generated_at`

Recommended age labels in the UI later:
- `fresh`
- `stale`
- `old`

The exporter does not need to assign those labels yet.

---

# Schema versioning

Use:
- `export_version: "v1"`

If breaking changes are made later:
- increment schema version
- keep frontend and exporter aligned explicitly

---

# First implementation recommendation

Implement only these outputs first:
- `manifest.json`
- `overview.json`
- `strategies.json`
- `runs.json`
- `experiments.json`
- `positions-open.json` once open-position semantics are verified clean enough

Then manually review the generated outputs before building any UI.

If the first snapshot already feels clear and trustworthy, proceed to the first static dashboard.
If not, fix the export layer first.

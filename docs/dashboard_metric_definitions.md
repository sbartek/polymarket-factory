# Dashboard Metric Definitions

## Purpose

This document defines the core metrics and status semantics for the PPLayouts external dashboard.

The goal is to make the exported dashboard snapshot trustworthy and interpretable before any frontend work begins.

If a metric is ambiguous, the exporter should either:
- compute it according to the rules below, or
- mark it as `unknown` / `unavailable` rather than faking precision.

## General principles

- Prefer **clarity over apparent completeness**.
- Prefer **explicit status labels** over clever inference hidden in code.
- Keep **active** and **legacy** views separate unless explicitly requested.
- If a metric mixes active and legacy data, that must be stated clearly.
- Time scope must always be explicit.

## Core status vocabularies

### Run status

Allowed values:
- `ok` — run completed successfully without fatal errors
- `warning` — run completed, but warnings/errors/skips exceeded a defined threshold or a meaningful subset of work failed
- `error` — run failed or ended in a clearly broken state
- `unknown` — status cannot be determined from stored data

Initial rule:
- use the stored run/job status if available and trustworthy
- downgrade `ok` to `warning` only if later exporter logic establishes that the run completed but had material issues worth surfacing
- if data is missing or contradictory, use `unknown`

### Strategy status

Allowed values:
- `active` — currently part of the active strategy stack
- `paused` — intentionally disabled but still part of current-era reporting context
- `legacy` — historical strategy no longer part of the current active stack and should not distort current interpretation
- `unknown` — cannot classify with confidence

Initial rule:
- use existing active-vs-legacy strategy classification already introduced in repo reporting
- paused strategies should remain distinct from legacy if the source data allows it
- if the data model cannot currently distinguish `paused` from `legacy`, export `legacy` for now and document the limitation in warnings

### Experiment status

Allowed values:
- `active` — experiment is currently in progress
- `planned` — defined but not yet active
- `review_due` — active/planned experiment has reached or passed a stated review point
- `completed` — experiment reached a documented conclusion
- `archived` — retained for history, not part of current active focus
- `unknown` — cannot be inferred confidently

Initial rule:
- derive from explicit metadata in experiment records where available
- if not explicit, infer conservatively from record structure and linked review artifacts
- prefer `unknown` over overconfident inference

## Time scopes

The dashboard should avoid mixing scopes invisibly.

Initial default scopes:
- `latest_run`
- `30d`
- `all_time`

Rules:
- every time-dependent metric should encode its scope in the field name unless it is shown only inside a clearly scoped object
- do not present a number like `realized_pnl` without an explicit scope in the export contract

## Exposure metrics

### `open_exposure_active`

Definition:
- the total current open exposure attributable to strategies classified as `active`

Requirements:
- exclude legacy strategies
- if exposure can be represented as either signed or absolute, exporter should choose one canonical form and document it in schema

Initial preference:
- use **absolute exposure** for top-level dashboard summary because it is easier to interpret as current risk footprint
- if signed exposure is useful later, export it separately as a different field

### `open_exposure_legacy`

Definition:
- the total current open exposure attributable to strategies classified as `legacy`

Purpose:
- to keep old positions visible without contaminating active interpretation

### `open_exposure`

Rule:
- avoid exporting an unqualified `open_exposure` in summary views
- prefer explicit variants like:
  - `open_exposure_active`
  - `open_exposure_legacy`
  - `open_exposure_total`

## Position metrics

### `open_position_count_active`

Definition:
- number of currently open positions attributed to active strategies

### `open_position_count_legacy`

Definition:
- number of currently open positions attributed to legacy strategies

### Open position

Definition:
- a trade/position record currently considered unresolved/open by the current broker/state model

Rule:
- do not redefine open/closed independently in the dashboard layer if the SQLite-backed trade model already has a reliable open/closed state
- if ambiguity exists, surface a warning

## PnL metrics

### `realized_pnl_30d`

Definition:
- realized profit/loss from closed positions within the last 30 days for the given scope

### `realized_pnl_all_time`

Definition:
- realized profit/loss across all available history for the given scope

Rules:
- keep active and legacy interpretations separate where useful
- do not combine realized and unrealized values into one headline metric
- if realized PnL calculation depends on assumptions still being stabilized, exporter should surface a warning note

## Activity metrics

### `recent_signals_count`

Definition:
- count of signals generated in the chosen recent scope for a strategy or the whole system

Initial scope:
- latest run for run-level displays
- 30 days for strategy summary unless otherwise specified

### `recent_decisions_count`

Definition:
- count of logged decisions in the chosen recent scope

Purpose:
- useful as a “system doing work vs silent” indicator
- should not be treated as a performance metric by itself

## Run health metrics

### `latest_run_status`

Definition:
- normalized status of the most recent run visible to the exporter

### `latest_run_duration`

Definition:
- elapsed duration for the latest run

### `errors_count`

Definition:
- count of errors associated with a run in exported reporting

Rule:
- the exporter must define what counts as an error source:
  - explicit logged errors
  - failed strategy checks
  - exception events
- do not inflate this metric with harmless informational messages

### `alerts`

Definition:
- a compact list of current noteworthy warnings requiring attention

Examples:
- latest run failed
- snapshot data partially missing
- experiment records malformed
- strategy classification inconsistent

Rule:
- alerts are for operationally meaningful issues, not every oddity in the data

## Strategy summary metrics

### `by_time_window`

Definition:
- grouped summary metrics split by the current project time-window taxonomy

Expected labels:
- `super_short`
- `intraday`
- `short`
- `medium`
- `long`
- `unknown`

Rule:
- exporter should use canonical normalized labels only

### `by_edge_type`

Definition:
- grouped summary metrics split by strategy edge type

Rule:
- use canonical normalized edge-type labels from the current taxonomy/reporting layer
- if missing, use `unknown`

## Experimentation metrics

### `active_experiment_count`

Definition:
- number of experiments currently classified as active current work

Initial rule:
- count experiments with status `active` or `review_due`
- do not count `planned`, `completed`, or `archived`

### `review_due`

Definition:
- explicit review date if present, otherwise null

Rule:
- do not invent dates from thin air
- if the experiment is clearly due for review but lacks a date, use status `review_due` and a null date with a warning/note where appropriate

### `linked_changes`
### `linked_reviews`

Definition:
- explicit lists of related artifact IDs

Rule:
- maintain these as references, not expanded blobs, in the first snapshot version

## Null / unknown policy

When data is missing or not trustworthy:
- use `null` for absent scalar values
- use `unknown` for enum-like status fields
- use `[]` for genuinely empty collections
- attach warnings in the exporter/manifest when missingness matters to interpretation

Never:
- substitute `0` for unknown
- substitute empty string for unknown status
- silently drop confusing records if they change interpretation materially

## MVP metric priorities

The first exporter/dashboard iteration should prioritize these as the most important reliable metrics:

1. `latest_run_status`
2. `latest_run_duration`
3. `open_exposure_active`
4. `open_position_count_active`
5. `open_exposure_legacy`
6. `open_position_count_legacy`
7. `active_strategy_count`
8. `active_experiment_count`
9. per-strategy status/exposure/activity summaries
10. experiment status / hypothesis / review-due summaries

Everything else is secondary until these are trustworthy.

## Known likely ambiguities to resolve during exporter implementation

These should be explicitly checked when building the exporter:
- whether paused strategies are distinguishable from legacy in current data
- whether top-level exposure should include only active strategies by default
- whether realized PnL calculations are already stable enough for headline use
- whether recent activity scope should be latest run or 30 days by default per view
- whether open positions data is clean enough for MVP inclusion

## Phase A execution-reality metrics

These metrics summarize the new signal-time execution checks.
They must be framed as **fill proxies / execution checks**, not actual fills or a full market-depth simulation.

### `execution_checks_30d`

Definition:
- count of rows in `signal_execution_checks` over the last 30 days

Purpose:
- indicates whether the Phase A instrumentation is actually collecting evidence

### `strategies_with_execution_checks_30d`

Definition:
- count of distinct strategies with at least one execution-check row in the last 30 days

### `avg_ev_after_slippage_50_pp_30d`

Definition:
- average `ev_after_slippage_50_pp` across Phase A execution checks in the last 30 days

Rule:
- present as a rough comparative metric only
- do not present as a realized-return metric

### `avg_max_size_positive_ev_30d`

Definition:
- average Phase A `max_size_positive_ev` in USD over the last 30 days

Rule:
- this is a proxy summary, not a live capacity guarantee

### `execution_source_confidence_counts_30d`

Definition:
- grouped counts of execution-check rows by `source_confidence`

Purpose:
- reminds the operator how much of the Phase A layer is grounded in direct quote fields versus fallback heuristics

### Per-strategy execution summary fields

For each strategy, the exporter may include:
- `execution_checks_count_30d`
- `avg_ev_after_slippage_10_pp_30d`
- `avg_ev_after_slippage_50_pp_30d`
- `avg_ev_after_slippage_100_pp_30d`
- `avg_max_size_positive_ev_30d`
- `avg_max_size_above_min_edge_30d`
- `execution_source_confidence_counts_30d`

Rules:
- use `null` where averages are not available
- use `0` only for true count fields
- if no checks exist, attach a warning rather than silently implying a strategy has execution evidence

## Recommendation

If a metric cannot be made trustworthy quickly, exclude it from MVP rather than presenting a persuasive lie.

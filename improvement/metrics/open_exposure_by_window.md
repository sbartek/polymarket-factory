# Metric Definition

- **metric_name:** open_exposure_by_window
- **owner:** Bartek
- **maturity:** usable

## Purpose

Track how much open exposure is allocated to each strategy time window.

## Formula

For each time window:

`sum(amount_usdc for open trades in that window)`

## Source

SQLite `trades` table, grouped by `time_window` for `status='open'`.

## Known limitations

- imported legacy trades may reflect backfilled metadata, not original explicit metadata
- exposure is not the same as realized risk or capacity

## Failure modes

- treating exposure as a complete risk metric
- ignoring active vs legacy split

## Companion metrics

- open exposure by strategy
- active vs legacy exposure
- realized ROI by time window

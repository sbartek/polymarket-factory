# Metric Definition

- **metric_name:** skip_reason_rate
- **owner:** Bartek
- **maturity:** usable

## Purpose

Understand which decision filters most often prevent signals from becoming positions.

## Formula

For a chosen time window / run window / strategy subset:

`count(decisions where decision='skip' and reason=R) / count(all decisions where decision='skip')`

## Source

SQLite `decisions` table.

## Known limitations

- strongly affected by fast-dry-run behavior
- can overstate a skip reason if candidate volume is tiny
- not a profit metric

## Failure modes

- interpreting skip frequency as proof a filter is wrong
- combining dry and live data without context

## Companion metrics

- opens by strategy
- signals generated
- recent run mode mix

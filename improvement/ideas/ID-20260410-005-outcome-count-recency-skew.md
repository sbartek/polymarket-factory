# Strategy Idea

- **idea_id:** ID-20260410-005
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** parked

## One-line thesis

Newer or recently updated count-bucket markets may show skewed pricing relative to older adjacent buckets because market attention is uneven.

## Why keep this around?

The theme is not impossible, but the current system does not have strong enough listing-age or update-age features to make it convincing.

## Why not now?

- missing data: reliable creation time and meaningful recency metadata at the bucket level
- missing infra: none urgent, but the feature set is too thin
- overlap with existing strategy: partial overlap with count-distribution strategies
- other reason: the thesis is weak enough that it should stay parked until stronger evidence appears

## What would need to be true to revive it?

- trustworthy age and update metadata for related outcome buckets
- evidence that recency skew adds value beyond structural oversum or drift logic
- examples of repeatable false pricing linked to bucket freshness

## Related files or notes

- strategy: VM-only parked generated `outcome_count_recency_skew`

## Promotion trigger

Promote this to `proposals/` only if a concrete data-backed recency feature emerges that explains real pricing errors.

# Strategy Idea

- **idea_id:** ID-20260410-008
- **date:** 2026-04-10
- **captured_by:** Codex
- **status:** parked

## One-line thesis

Markets that moved on older information may partially revert as the informational value of the catalyst decays.

## Why keep this around?

The high-level concept is sensible, but it is too vague on its own and overlaps with stronger news-linked strategies already in the repo.

## Why not now?

- missing data: better event timestamping and clearer catalyst linkage would help
- missing infra: none mandatory, but the logic is underspecified
- overlap with existing strategy: overlaps with `ev_news` and `news_impact_fade_by_recency`
- other reason: without a sharper definition, it is just a blurry version of existing news-fade logic

## What would need to be true to revive it?

- a concrete definition of "information decay" distinct from simple recent-news fade
- data showing that older catalysts produce a predictable second-stage reversion pattern
- a clear reason not to fold it into `news_impact_fade_by_recency`

## Related files or notes

- strategy: VM-only parked generated `information_decay_recency_weighted`
- strategy: `news_impact_fade_by_recency`
- strategy: `ev_news`

## Promotion trigger

Promote this to `proposals/` only if it becomes a clearly differentiated post-news decay strategy rather than a duplicate of existing news logic.

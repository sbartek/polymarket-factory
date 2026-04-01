# Celebrity Tabloid Strategy

- Strategy name: `celebrity_tabloid`
- Status: alert-only / paper-test candidate
- Proposal source: `improvement/proposals/PR-20260401-001-choose-only-celebrity-based-events-and-search-only-in-gossip.md`

## Edge Thesis

Celebrity/personality markets can lag when rumor-driven entertainment coverage breaks first in gossip/tabloid outlets instead of mainstream news. The edge is not "all celebrity news"; it is narrow, near-dated, liquid-enough markets where multiple gossip-style headlines point in the same direction and Polymarket has not fully repriced yet.

This MVP is intentionally fail-closed:
- no corroborating gossip coverage => no alert
- ambiguous or contradictory coverage => no alert
- broad fame/pop-culture markets without a concrete event predicate => no alert

## Filters

- market must look celebrity/entertainment related from title/tags/category text
- exclude obvious politics, sports, crypto, macro, and generic pop-culture trend books
- require a concrete event family in the title:
  - `romance_up` (`dating`, `engaged`, `married`, `wedding`, `reconcile`)
  - `romance_down` (`breakup`, `split`, `divorce`, `cheating`)
  - `pregnancy` (`pregnant`, `expecting`, `baby`)
  - `scandal` (`arrested`, `lawsuit`, `rehab`, `hospitalized`)
- require identifiable person/celebrity names from title or tags
- require:
  - volume >= `$10k`
  - close date within `1-45` days
  - YES price between `12%` and `88%`

## Candidate Scoring

Deterministic pre-score:
- + event-family match
- + entertainment / celebrity tag match
- + two or more detected person-name tokens
- + stronger liquidity / recency
- + price near the middle, where repricing room exists

Gossip corroboration score:
- search only entertainment/tabloid-style sources (`people.com`, `tmz.com`, `pagesix.com`, `usmagazine.com`, `eonline.com`, `okmagazine.com`, `dailymail.co.uk`)
- count only hits mentioning at least one extracted celebrity name
- reward hits whose title/snippet matches the market's event family
- penalize explicit denial / contradiction language

Alert threshold:
- emit only when deterministic candidate score is strong enough and gossip corroboration is both:
  - present (`>= 2` usable hits)
  - directional (`support score >= threshold`, contradiction score limited)

## Likely Failure Modes

- rumor headlines are recycled, stale, or based on weak sourcing
- extracted names are wrong or incomplete, causing bad queries
- celebrity tags leak into unrelated books and create false positives
- event wording is too vague for deterministic family mapping
- gossip sources contradict each other or publish pure speculation
- price action is already efficient before scan time

## Validation Plan

- keep `alert_only=True`, `trading_enabled=False`
- run for at least 10 live cycles before any promotion discussion
- inspect:
  - all emitted alerts
  - at least 30 persisted candidate-check rows
  - hit-rate by event family
  - duplicate/cluster spam around the same couple/person
- kill or tighten if any of the following happens:
  - repeated alerts on obviously rumor-only garbage
  - < 20% of alerts look directionally sensible on manual replay
  - candidate table is dominated by non-celeb or weakly defined markets
  - queries frequently fail or return sparse/noisy results

## MVP Scope

- deterministic market filtering
- lightweight DDGS-backed entertainment/tabloid lookup
- no LLM dependency
- no auto-betting
- few alerts is acceptable; silence is preferable to garbage

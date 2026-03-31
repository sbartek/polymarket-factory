# PPLayouts Implementation Plan — 2026-03-31

Concrete plan for:
- `spread_arb_v2`
- `stale_market`
- `correlated_pairs`

Goal: improve strategy quality, shorten feedback loops, and move the portfolio toward edge classes that are mechanical, auditable, and less LLM-fragile.

---

## Phase 0 — Immediate operational changes

Before building new strategies:

1. Remove or disable from `STRATEGIES` registry:
   - `fade_certainty`
   - `weather_edge`

2. Keep active:
   - `ev_news`
   - `resolution_hunter`
   - `spread_arb`

3. Add TODO comments in code for future `v2` upgrades rather than silently forgetting why changes were made.

Suggested near-term order:
1. `spread_arb_v2`
2. `stale_market`
3. tighten `ev_news`
4. tighten `resolution_hunter`
5. `correlated_pairs`

---

# 1) `spread_arb_v2`

## Objective
Preserve the structural basket-arbitrage idea while avoiding capital lock-up and weak-quality baskets.

## Why first
- least dependent on LLM judgment
- conceptually clean
- easiest to evaluate after resolution
- already integrated into current architecture

## Proposed rule changes

### Universe filters
Only consider events where:
- outcomes are mutually exclusive and collectively exhaustive enough to trust
- active outcomes >= 3
- event volume >= `MIN_VOLUME_V2` (e.g. 15k–25k)
- days to close within `7 <= d <= 90`

### Pricing filter
Require:
- `sum(YES) < 0.90` initially for higher-quality baskets
- later test threshold grid: `0.88`, `0.90`, `0.92`

### Basket quality checks
Reject events if:
- one “other/none/field” outcome is missing when clearly expected
- only a subset of relevant outcomes appears active
- submarkets look stale/inconsistent structurally
- one leg dominates too heavily and makes the basket unattractive

### Position management
- open at most `N` new baskets per run, e.g. 2–4
- cap total simultaneous arb baskets, e.g. 10
- store and evaluate basket identifier at event level
- track basket cost, implied locked profit, and hold duration

## Code changes

### Files to touch
- `factory/strategies/spread_arb.py`
- optionally `factory/models.py` if basket metadata is worth formalizing
- optionally `data/trades.csv` handling if event/basket grouping metadata is added
- `eval/report.py` for basket-level reporting later

### Recommended implementation approach

#### Step 1 — add stronger filters
Add constants such as:
- `MIN_VOLUME = 15000`
- `MIN_DAYS_TO_CLOSE = 7`
- `MAX_DAYS_TO_CLOSE = 90`
- `ARB_THRESHOLD = 0.90`
- `MAX_NEW_BASKETS_PER_RUN = 3`

#### Step 2 — add basket scoring
For each event basket, compute:
- number of legs
- total sum of YES prices
- gap to 1.0
- expected locked-in return
- days to close
- volume

Sort candidate baskets by something like:
`score = gap_pp * liquidity_weight / sqrt(days_to_close)`

No need for fancy optimization yet. Just make it obviously better than FIFO opening.

#### Step 3 — enforce basket caps
Before opening legs for a basket:
- check how many existing open baskets already exist
- skip weaker baskets when inventory is full

#### Step 4 — add reporting
At minimum, include basket-level summary in logs:
- event title
- legs
- sum(YES)
- gap
- days to close

## Evaluation criteria
After enough closures, evaluate:
- basket-level ROI
- hold duration
- number of resolved profitable baskets
- frequency of false arb due to incomplete outcome sets

## Success condition
A strategy that opens fewer, better, shorter-duration baskets and produces interpretable realized outcomes.

---

# 2) `stale_market`

## Objective
Exploit markets that have not repriced after relevant new information.

## Why this is next
This is likely the best next edge class:
- specific market inefficiency
- easier to reason about than generic freeform EV
- complements `ev_news` without duplicating it

## Core hypothesis
Some Polymarket prices become stale when:
- trading activity is low
- relevant news arrives
- market participants do not update quickly

The edge is not “news says outcome X.”
The edge is “the market clearly has not moved enough after news that should matter.”

## Minimal viable version

### Candidate generation
From top markets, select candidates where:
- volume is decent overall but likely low recent activity
- price is in a tradable middle range, e.g. `0.10–0.85`
- closes in `3–45 days`
- title is clearly understandable / searchable

Because recent-trade timestamps may not be easily available from current feed, MVP can use proxy heuristics:
- medium overall volume, but not top frenzy markets
- price not at extremes
- event in active news topic categories (politics, macro, geopolitics, crypto)

### News check
For each candidate, fetch 3–5 recent news items.
Use either heuristic filters or Claude to answer:
- Did meaningful new information arrive recently?
- Does it materially favor YES or NO?
- Does the current price appear slow versus that information?

### Trade threshold
Only open when all are true:
- news relevance is high
- directional signal is clear
- estimated edge exceeds threshold, e.g. `>= 12pp`
- confidence is `medium` or `high`

## Guardrails
- max 1 trade per topic cluster per run
- max 2–3 total new stale-market trades per run
- ignore low-quality clickbait/news-poor candidates
- ignore markets with ambiguous resolution criteria

## Code sketch
Create:
- `factory/strategies/stale_market.py`

Potential helper reuse:
- DDGS news fetch from `ev_news` / `resolution_hunter`
- `call_claude()` prompt pattern
- feed helpers for prices, URLs, closing dates

## Suggested algorithm

### Step 1 — candidate filter
Filter markets by:
- close window
- volume
- price band
- keyword categories

### Step 2 — detect stale-likelihood
Rank candidates by stale-likelihood score:
- non-extreme price
- mid-level volume
- recent-news-heavy topic
- absence of huge current market move proxies

### Step 3 — LLM judgment on top K only
Ask Claude something like:
- summarize recent info
- estimate whether this information should have moved the market materially
- output `outcome`, `p_hat`, `ev_pp`, `confidence`, `reason`

### Step 4 — dedupe by topic
If three Iran markets all light up, open only the best one unless diversification logic later says otherwise.

## Parameters to start with
- `min_ev_pp = 12`
- `max_position_usdc = 12`
- candidate pool per run: top 15–20 filtered markets
- open max 2 new positions/run

## Evaluation criteria
Track separately:
- average holding period
- realized ROI
- topic concentration
- proportion of trades driven by geopolitics vs macro vs elections
- whether news relevance actually matched market resolution path

## Success condition
A small-number, high-conviction strategy that finds lagging reprices better than `ev_news`.

---

# 3) `correlated_pairs`

## Objective
Find logically linked markets priced inconsistently and trade the cheaper implication.

## Why later than `stale_market`
Good strategy class, but requires more ontology and logic mapping. Better built after the portfolio has one more clean signal source.

## Core hypothesis
Some market pairs violate basic logical or probabilistic consistency.
Examples:
- parent/child event links
- necessary-but-not-sufficient chains
- election/nomination path dependencies
- escalation/de-escalation geopolitics

## MVP scope
Keep it narrow. Do **not** try to solve all logic on day one.

Start with 2–3 templates only.

### Template A — prerequisite pair
Example shape:
- Market A: candidate wins primary
- Market B: candidate wins presidency

Constraint intuition:
- `P(B) <= P(A)` if A is a prerequisite

If `P(B)` is materially above `P(A)`, one side is mispriced.

### Template B — stronger/weaker event pair
Example:
- Market A: “US-China trade war escalates”
- Market B: “Trump imposes 50% tariffs on China”

Constraint intuition:
- stronger/narrower event should not be more likely than broader/weaker parent event unless wording justifies it

### Template C — mutually reinforcing geopolitical paths
Example:
- war event vs ceasefire event vs sanctions escalation

This likely requires more manual curation first.

## Implementation approach

### Step 1 — pair discovery
Use title/tag heuristics plus optional Claude mapping to identify candidate pairs among top markets.

For MVP, manually define a few regex/template families:
- nomination ↔ election win
- broad event ↔ specific event
- broad category ↔ sub-event

### Step 2 — consistency rule
For each pair, define:
- expected inequality or relationship
- minimum gap to act, e.g. `>= 10pp`

### Step 3 — trade decision
Open only when:
- pair relationship is high-confidence
- wording is genuinely linked, not just semantically similar
- volume is acceptable on both markets
- both close within a reasonable horizon

## Likely position style
MVP can remain **single-leg**, not true two-sided relative-value execution:
- buy the obviously underpriced leg
- optionally buy NO on the obviously overpriced leg later

Single-leg is simpler and fits current broker/trade model.

## Code sketch
Create:
- `factory/strategies/correlated_pairs.py`

Potential supporting module later:
- `factory/pair_rules.py`

## Suggested prompt/output for LLM-assisted mapping
Input:
- two market titles
- prices
- close dates

Ask Claude to output only if relationship is one of:
- prerequisite
- broader_event
- narrower_event
- unrelated

Then compute pricing inconsistency mechanically outside the LLM.

## Parameters to start with
- `min_ev_pp = 10`
- `max_position_usdc = 10`
- max 1–2 trades/run
- only top few high-confidence pairs

## Evaluation criteria
Track:
- pair template type
- predicted relationship
- realized ROI by template
- false positive rate from bad semantic mapping

## Success condition
A low-frequency, interpretable strategy that captures obvious logical inconsistencies without turning into semantic soup.

---

# 4) Tightening current survivors

## `ev_news_v2`
Recommended updates:
- close window: `7–60 days`
- stronger volume floor
- reject weak news-market relevance
- enforce topic concentration cap
- only medium/high confidence trades
- max 2–3 trades/run

## `resolution_hunter_v2`
Recommended updates:
- broaden candidate pool slightly
- prioritize searchable, clearly resolvable markets
- add keyword heuristics for likely-resolved events before Claude call
- continue requiring high confidence for actual trade opening

---

# 5) Suggested development order

## Week 1
1. Disable `fade_certainty`
2. Disable `weather_edge`
3. Implement `spread_arb_v2` filters and basket caps
4. Add basket-level logging

## Week 2
1. Implement `stale_market` MVP
2. Paper-run with very low trade count
3. Tighten `ev_news`

## Week 3
1. Tighten `resolution_hunter`
2. Build `correlated_pairs` MVP with only 1–2 pair templates

## Week 4
1. Review realized outcomes
2. Compare strategy-level cadence, concentration, and hold times
3. Decide whether to expand `correlated_pairs` or revive `weather_edge_v2`

---

# 6) Concrete coding checklist

## Registry and strategy management
- [ ] Remove `FadeCertaintyStrategy()` from `STRATEGIES`
- [ ] Remove `WeatherEdgeStrategy()` from `STRATEGIES`
- [ ] Add comments explaining pause rationale

## `spread_arb_v2`
- [ ] tighten close window
- [ ] tighten arb threshold
- [ ] raise volume floor
- [ ] cap baskets per run
- [ ] add basket scoring
- [ ] add basket-level logging

## `stale_market`
- [ ] create strategy file
- [ ] candidate filter
- [ ] news fetch
- [ ] Claude prompt/output schema
- [ ] topic dedupe
- [ ] run-level trade cap

## `ev_news_v2`
- [ ] add close-window filter
- [ ] add liquidity filter
- [ ] add confidence filter
- [ ] add topic cap

## `resolution_hunter_v2`
- [ ] improve candidate ranking
- [ ] keyword heuristics for likely resolved events
- [ ] slightly broaden candidate pool

## `correlated_pairs`
- [ ] create strategy file
- [ ] implement template family 1: prerequisite
- [ ] implement template family 2: broader/narrower event
- [ ] mechanical gap rule
- [ ] optional Claude relationship classifier

---

# Bottom line

Recommended path:
- stop the obvious bleeding (`fade_certainty`, `weather_edge`)
- make `spread_arb` shorter-duration and higher-quality
- build `stale_market` next
- then add `correlated_pairs`

That gives PPLayouts a portfolio built around:
- structural mispricing
- stale repricing
- delayed information
- resolution lag
- logical inconsistency

A much healthier lineup than hoping the weather and the crowd are drunk in exactly the same direction.
# PPLayouts Implementation Plan — 2026-03-31

Concrete plan for:
- `spread_arb_v2`
- `stale_market`
- `correlated_pairs`
- 2026-04-02 revision: Phase A execution-reality instrumentation

Goal: improve strategy quality, shorten feedback loops, and move the portfolio toward edge classes that are mechanical, auditable, and less LLM-fragile.

---

## 2026-04-02 revision — execution reality / capacity plan

After review, the broader execution-capacity proposal was narrowed intentionally.

### Critical review summary

The original plan was directionally correct, but too ambitious for a first slice.
Main risks:
- fake precision if fill estimates are not grounded in observable quote/depth data
- over-investing in dashboards before signal-time execution data exists
- annualized dollar projections becoming unstable too early
- forcing one generic framework across very different strategies

### Approved direction

Build this in three stages:

#### Phase A — must-have instrumentation (implement first)

Add a small shared execution-reality layer at **signal time**.
For every generated signal, persist:
- observed quote price used by the strategy
- observed `bestBid` / `bestAsk` / spread when available
- order-min-size if available
- a conservative liquidity proxy from available market/event fields
- fill-price proxies for size buckets: `10 / 25 / 50 / 100 / 250` USD
- slippage-adjusted EV for those size buckets
- max size with positive EV
- max size still above the strategy's configured `min_ev_pp`
- a source-confidence label describing how much direct quote/liquidity data the proxy used

Important constraints:
- label these as **execution checks / fill proxies**, not real fills
- do **not** treat them as a full order-book simulator
- do **not** block trading on this yet; Phase A is measurement first

Initial deliverables:
- shared helper layer for execution snapshots
- SQLite persistence table for signal execution checks
- runner integration to log one execution check per generated signal
- one CLI inspection script for operator review

#### Phase B — strategy-level summaries (only after enough logged evidence)

Once Phase A data exists for enough runs/signals, add:
- summary by strategy of slippage-adjusted EV at meaningful sizes
- opportunity frequency and max-positive-EV size distributions
- capital lock-up stats where applicable
- scenario views for monthly economics

This stage should stay exploratory and avoid pretending to know annual profit too early.

#### Phase C — business viability layer (only after trust is earned)

Only after Phase A/B metrics look trustworthy, add:
- benchmark vs passive 5%
- strategy-level worth-doing verdicts
- dashboard surfacing
- promotion / keep-kill guidance that references execution evidence

### Strategy-class note

The shared Phase A layer should remain thin.
Different strategy classes will still need different interpretation later:
- `spread_arb`: basket-level structural capacity
- `ev_news` / `stale_market`: latency and crowding sensitive
- `resolution_hunter`: more resolution-certainty driven than depth-driven
- alert-only screeners: measure first, avoid over-instrumenting too early

### Explicit non-goals for Phase A

Do **not** attempt yet:
- full live CLOB simulation
- exit-side microstructure modeling for all strategies
- annualized business-value headline metrics
- automatic keep/kill decisions based on tiny samples
- dashboard-first work

---

## 2026-04-03 revision — benchmark-first autonomous improvement loop

After reviewing the `autoagent` pattern, the useful idea is **not** the single-file harness layout.
The useful idea is the stricter loop:
- define an explicit directive
- constrain the edit surface
- run an evaluation
- keep or discard changes based on score

For `polymarket-factory`, this should be adapted carefully.
This repo is a trading/research system with slower and noisier feedback than a coding benchmark, so autonomous editing is only acceptable when tied to stable evidence.

### Critical review summary

Main conclusions from the review:
- do **not** collapse the factory into a single editable harness file
- do **not** let autonomous generation edit runner / broker / live-trading code paths by default
- do **not** use weekly realized P&L alone as the optimization loop for autonomous edits
- do use a benchmark-first keep/discard loop once replay data and execution checks are strong enough

### Approved direction

Build autonomous improvement in four stages:

#### Stage 1 — directive and edit-boundary discipline

Before any new autonomous cycle, define a short experiment brief similar in spirit to `program.md`.
That brief should specify:
- target strategy family or problem class
- files the agent may edit
- files the agent may not edit
- evaluation metric
- stop conditions
- promotion gate

Initial allowed edit surface:
- `factory/strategies/generated/`
- `improvement/proposals/`
- `improvement/experiments/`
- `improvement/reviews/` stubs

Initial forbidden edit surface unless a human explicitly approves:
- `factory/runner.py`
- broker / live execution paths
- DB schema used by production runs
- notification and operator-facing safety paths

#### Stage 2 — offline replay benchmark

Before trusting autonomous keep/discard decisions, build an offline replay benchmark using existing factory evidence:
- persisted run logs
- decision logs
- signal execution checks
- closed-trade outcomes where attribution is clean

The benchmark should optimize for:
- candidate quality
- calibration / replay precision
- execution realism
- duplicate / overlap control

It should **not** optimize directly for idea count or raw alert volume.

#### Stage 3 — score-gated generated strategies

Generated strategies should remain:
- alert-only on creation
- isolated in `factory/strategies/generated/`
- easy to archive or unregister

A generated strategy should only remain active if it clears one of these gates:
- replay benchmark score beats a baseline
- fixed paper-review window shows acceptable alert quality with supporting evidence

Auto-generation without a keep/discard gate is churn, not research.

#### Stage 4 — promotion after evidence, not before

Only after replay and alert-only evidence look credible should a human consider:
- enabling paper trading
- adding promotion criteria
- allowing edits outside the generated-strategy sandbox

Live-path changes remain human-reviewed work.

### 2026-04-03 delivered runtime boundary

The factory now has an explicit runtime environment split:
- `research` — signal logging only
- `paper` — paper-only positions and resolution
- `live` — real-money execution for explicit live-only strategies

Operational follow-through:
- keep paper and live as separate launchd entrypoints
- keep generated strategies blocked from `live`
- treat `live_ready=True` as a prerequisite, not the whole safety model

### Explicit non-goals for this loop

Do **not** attempt yet:
- autonomous edits to live trading or execution infrastructure
- autonomous refactors across the whole repo
- optimization directly on tiny realized P&L samples
- “auto-approved” generated strategies without a benchmark or review gate
- replacing the current modular architecture with a single-file harness

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

## Week 5
1. Define the first autonomous-improvement experiment brief template
2. Restrict generated-strategy edits to the sandboxed paths above
3. Design the first offline replay benchmark from run/decision/execution data
4. Replace auto-approval with score-gated keep/discard rules

## Week 6
1. Make generated-strategy lifecycle visible in the dashboard
2. Add replay benchmark slice breakdowns by `edge_type` and `time_window`
3. Add directional benchmark labels from price-window moves
4. Persist market snapshot observations for future benchmark labeling

## Week 7
1. Let fresh runs accumulate `market_observations`
2. Track benchmark label coverage by strategy
3. Add dashboard/reference visibility for observation coverage
4. Decide whether a backfill or retention policy is needed for `market_observations`

## Week 8
1. Make generated-strategy retention coverage-aware, not score-only
2. Keep low-evidence generated strategies in `pending_benchmark_review`
3. Archive only when both score and evidence quality clear the gate
4. Use dashboard coverage views to monitor whether the stricter gate is too conservative

## Week 9
1. Persist raw fetched market snapshots per run for future reconstruction
2. Record explicitly that historical backfill is not feasible from current local artifacts
3. Let future runs build reconstructible history organically
4. Revisit whether a retention policy is needed once raw snapshot volume is visible

## Week 10
1. Add project storage monitoring to the dashboard
2. Define raw snapshot retention at 2 years
3. Alert near 100 GB project storage before hard pressure appears
4. Defer cleanup/compression until growth justifies it

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

## Autonomous improvement loop
- [x] create a short experiment-brief template for autonomous runs
- [x] define allowed vs forbidden edit paths
- [x] build first replay benchmark from logged run / decision / execution evidence
- [x] add a baseline comparison for generated strategies
- [x] remove unconditional auto-approval from the aggressive generation workflow
- [x] require review-gated or score-gated retention for generated modules
- [x] show generated lifecycle state in the dashboard
- [x] add strategy-slice replay benchmark breakdowns
- [x] derive directional labels from price-window moves
- [x] persist market snapshot observations for future labeling
- [x] expose market-observation coverage in dashboard/reference
- [x] add a benchmark coverage metric to generated-strategy retention decisions
- [x] decide whether to backfill old runs or wait for organic coverage growth
- [x] persist raw per-run market snapshots for future reconstruction
- [x] add dashboard monitoring for project/raw-snapshot storage
- [x] define raw snapshot retention policy (2 years)
- [x] alert near 100 GB project storage
- [ ] add retention/cleanup policy for `market_observations` if table growth becomes material
- [ ] add pruning or compression for raw snapshot archives if storage growth justifies it

---

# Bottom line

Recommended path:
- stop the obvious bleeding (`fade_certainty`, `weather_edge`)
- make `spread_arb` shorter-duration and higher-quality
- build `stale_market` next
- then add `correlated_pairs`
- keep the benchmark-first autonomous strategy loop as the control layer around generated strategies
- historical backfill is not feasible from current local artifacts, so coverage now grows forward from stored raw snapshots + observations
- next focus: grow label coverage and observation coverage rather than adding more autonomous generation

That gives PPLayouts a portfolio built around:
- structural mispricing
- stale repricing
- delayed information
- resolution lag
- logical inconsistency

A much healthier lineup than hoping the weather and the crowd are drunk in exactly the same direction.

# PPLayouts Strategy Review — 2026-03-31

Based on live paper-trade data in `data/trades.csv` and current strategy implementations in `factory/strategies/`.

## Executive Summary

### Recommended actions now

- **Pause / kill immediately:** `fade_certainty`, `weather_edge`
- **Keep running with tighter filters:** `ev_news`, `resolution_hunter`
- **Refactor and keep as core structural strategy:** `spread_arb`

### Current closed-trade verdicts

- `fade_certainty`: **KILL**
- `weather_edge`: **KILL in current form**
- `ev_news`: too early
- `spread_arb`: too early, but structurally promising
- `resolution_hunter`: too early, but promising edge class

---

## Snapshot of current performance

From `data/trades.csv`:

- `weather_edge`: 136 total / 82 closed / 54 open
- `spread_arb`: 79 total / 0 closed / 79 open
- `fade_certainty`: 37 total / 6 closed / 31 open
- `ev_news`: 15 total / 0 closed / 15 open
- `resolution_hunter`: 1 total / 0 closed / 1 open

Weekly eval output:

- `fade_certainty`: 0% WR, -100.0% ROI on 6 closed trades → **KILL**
- `weather_edge`: 45% WR, -19.5% ROI on 82 closed trades → **KILL**

---

## Strategy-by-strategy review

## 1) `fade_certainty`

### Current thesis
Prediction markets at extreme prices (>93% or <7%) are systematically overconfident and can be faded.

### What the data says
- Closed trades: 6
- Win rate: 0%
- ROI: -100%

### Diagnosis
This is failing hard enough that it should not continue in current form. The implementation is too blunt:

- Assumes extreme pricing is miscalibrated by default
- Uses static fade amounts
- Still captures novelty / sports / event-driven markets where extremes may be justified
- Lacks category-specific filtering
- Has no news or market microstructure validation

### Decision
**Pause immediately.**

### If ever revived
Only as a much narrower subtype, for example:
- political outrights only
- no sports / novelty / one-off entertainment
- add liquidity and market age filters
- require stale-price evidence or external disagreement

---

## 2) `weather_edge`

### Current thesis
Open-Meteo ensemble probabilities can beat Polymarket crowd pricing on daily temperature bucket markets.

### What the data says
- Closed trades: 82
- Win rate: 45%
- ROI: -19.5%

### Diagnosis
This is the most informative loser: there is some apparent signal, but execution/selection is not strong enough.

Likely issues:
- Too many correlated bets per city/day
- Too many buckets traded per weather event
- EV threshold likely too low for noisy bucket outcomes
- Same-day / near-resolution markets may be too messy
- Exact bucket mapping may not line up cleanly with ensemble-derived probabilities
- Correlated exposure means a bad calibration day hurts many positions at once

### Decision
**Pause in current form.**

### Salvage path (`weather_edge_v2` only if desired later)
- Trade only the strongest 1–2 buckets per city/event
- Raise EV threshold materially
- Avoid same-day markets; prefer 1–3 day horizon
- Add city / market-type postmortem analysis before reactivation
- Consider skipping markets where adjacent buckets all look similarly priced

---

## 3) `ev_news`

### Current thesis
Fresh news is not fully incorporated into prediction market prices, creating exploitable mispricings.

### What the data says
- 15 open
- 0 closed
- Too early for performance verdict

### Strengths
- Plausible edge source
- Flexible across topics
- Small sizes limit damage while learning
- Can find non-obvious opportunities when markets are slow to absorb breaking developments

### Risks
- LLM-heavy pipeline
- Topic selection may be noisy or drift toward headline bait
- Can open multiple correlated positions in one narrative cluster
- Quality of edge depends heavily on news relevance matching

### Decision
**Keep running in paper, but tighten aggressively.**

### Recommended changes
- Restrict to markets closing in roughly **7–60 days**
- Require stronger liquidity threshold
- Reject weak news-to-market relevance matches
- Limit number of trades per topic cluster per run
- Require confidence = `medium` or `high`
- Add a topic dedupe / concentration cap per run

### Goal
Turn it from “news-shaped speculation” into a focused delayed-information strategy.

---

## 4) `spread_arb`

### Current thesis
In multi-outcome markets where exactly one outcome resolves, if the sum of YES prices is sufficiently below 1.0, buying the full basket creates near-guaranteed profit.

### What the data says
- 79 open
- 0 closed
- No realized performance yet

### Why this is promising
This is the cleanest strategy concept in the portfolio:
- structural edge
- mechanical rules
- low dependence on LLM judgment
- easy to audit after resolution

### Main problem
It is opening too many **long-dated baskets**, including markets resolving far in the future. That creates:
- very slow feedback loops
- tied-up paper capital
- difficult live deployment logistics
- noisy portfolio optics

### Decision
**Keep, but refactor now.**

### Recommended changes (`spread_arb_v2`)
- Tighten close window to roughly **7–90 days**
- Raise quality threshold from `sum(YES) < 0.93` to maybe **< 0.90** (or test both)
- Raise minimum volume
- Cap simultaneous baskets
- Score at the **basket** level, not only by individual legs
- Prefer markets with stable and clearly exhaustive outcome sets
- Avoid baskets with suspicious or obviously missing outcomes

### Goal
Make this the portfolio’s “boring structural alpha” strategy.

---

## 5) `resolution_hunter`

### Current thesis
Some markets continue trading at non-trivial prices after the real-world event has already resolved, due to settlement lag or market inattention.

### What the data says
- 1 open
- 0 closed
- Too early to judge P&L

### Why this is attractive
This is one of the most believable edge classes in prediction markets:
- settlement lag is real
- market participants are often slow or distracted
- probability should collapse toward certainty once an event has already happened

### Main problem
Signal frequency is very low right now.

### Decision
**Keep running, but improve candidate generation.**

### Recommended changes
- Broaden candidate pool slightly
- Focus on markets with:
  - clear binary real-world resolution criteria
  - strong recent news flow
  - near-term close
  - price still in the 15–75% range
- Add keyword heuristics before Claude analysis to surface likely-resolved events
- Prefer markets where the resolution condition can be validated from 1–3 reputable sources

### Goal
Increase hit rate without turning it into a hallucination factory.

---

## Portfolio-level recommendations

## Immediate portfolio actions

### Pause now
- `fade_certainty`
- `weather_edge`

### Keep paper-running
- `ev_news`
- `resolution_hunter`

### Refactor and continue
- `spread_arb`

## Why this portfolio is cleaner
This yields a more coherent stack:

- `spread_arb` → structural pricing edge
- `ev_news` → delayed information edge
- `resolution_hunter` → post-resolution lag edge

That is a much better research portfolio than mixing in blunt fades and noisy weather bucket spam.

---

## Recommended build order for next strategies

Priority order:

1. **`stale_market`**
2. **`correlated_pairs`**
3. **`polling_vs_market`**
4. `crypto_options_basis`
5. `base_rate` (better as a filter than a standalone first build)

### Why `stale_market` is next
- specific and believable edge
- closer to actual market inefficiency than generic “news says so” logic
- easier to validate ex post than freeform EV estimation

### Why `correlated_pairs` is next
- exploits logical inconsistency
- less dependent on absolute probability estimation
- naturally complements `ev_news`

### Why `polling_vs_market` is later but attractive
- clean external benchmark
- auditable
- valuable where active election inventory exists

---

## Recommended strategy stack after refactor

Short-term target stack:

- `spread_arb_v2`
- `stale_market`
- `ev_news_v2`
- `resolution_hunter_v2`
- `correlated_pairs`

This produces better diversification by edge type and should yield faster learning loops.

---

## Bottom line

If we were allocating actual trust instead of paper pretend-money:

- `fade_certainty` has already earned the shovel
- `weather_edge` gets paused until proven less drunk
- `spread_arb` is the best structural candidate
- `ev_news` and `resolution_hunter` are worth continued paper testing with tighter filters
- `stale_market` should be the next build

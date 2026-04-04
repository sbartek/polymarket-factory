# Strategy Proposal

    - **proposal_id:** PR-20260404-002
    - **date:** 2026-04-04
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** approved
    - **approval_note:** Unblocked by using TF-IDF kNN over resolved market titles instead of hand-built table. Backfill from Gamma API provides thousands of resolved markets as training data.

    ## Plain-language idea

    New Market Base Rate Divergence

    ## Structured thesis

    When a new Polymarket market opens (< 48h old), the initial price is often set by a small number of LPs anchoring near 50% as a safe default, regardless of the historical base rate for that event class. Bettors with a reference class (e.g., incumbent re-election rates, pre-season championship favorite hit rates, historical litigation settlement rates) can extract value by betting against this anchor bias before the market crowd corrects it. This is an information edge available for a limited window.

    ## Candidate metadata

    - **proposed_name:** base_rate_anchor
    - **edge_type:** model_vs_market
    - **time_window:** medium
    - **market_types:** ['Electoral/incumbent markets (well-established base rates from prior cycles)', 'Sports championship outrights opened at season start', "Legal/regulatory outcome markets (e.g., 'Will lawsuit X settle?')", 'Company IPO or acquisition completion markets']
    - **likely_inputs:** ['Market age (hours since creation)', 'Current market price', 'External base rate lookup: pre-compiled reference table by market category (e.g., incumbent win rate by approval band, championship odds vs seed/ranking)', 'Market title keyword classifier to match to a base rate bucket']

    ## Candidate logic

    ### Entry

    Alert when: (1) market is < 48h old, (2) total volume < $5,000 (still in anchor zone), (3) keyword classifier assigns market to a known base-rate bucket with confidence >0.7, (4) |market_price - base_rate| > 12 percentage points. Bet in the direction of the base rate.

    ### Exit / hold

    Close at 7-day mark OR when market volume crosses $25,000 (crowd has priced in), whichever is first. Also close if price moves to within 3pp of base rate (target achieved). Hard stop at 15pp adverse move.

    ## Expected failure modes

    - Base rate table is wrong or the wrong category is matched — garbage in, garbage out
- Market opened late (event already partially resolved) making the base rate irrelevant
- The 50% anchor may already reflect informed LP pricing, not ignorance
- Very thin markets: alert fires but size is limited to $5–10 before moving the price
- Base rates from prior cycles may not apply to novel events (e.g., first AI regulation vote)
- Keyword classifier misfires on ambiguous titles, assigning wrong base rate bucket

    ## Validation plan

    Hand-build a reference table of 8–12 event categories with historical base rates and confidence intervals. Run classifier against last 6 months of Polymarket market titles; manually audit 50 matches for precision. Paper trade all qualifying signals for 60 days. Track: (a) classifier accuracy, (b) whether market price converged toward base rate within 7 days, (c) P&L per signal. Require >60% directional accuracy before activating real capital.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

# Strategy Proposal

    - **proposal_id:** PR-20260404-001
    - **date:** 2026-04-04
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** archived
    - **deferred_reason:** Needs ~1 week of hourly price history. Observer running every 30min since 2026-04-04. Revisit after 2026-04-11 when we have enough data for hour-of-day distributions.

    ## Plain-language idea

    Overnight Liquidity Gap Fade

    ## Structured thesis

    Polymarket order books are dominated by US/EU traders. During low-liquidity hours (roughly 01:00–08:00 ET), thin books allow small market orders to move prices disproportionately. These dislocations tend to revert once normal volume resumes. The edge is purely structural: a given price move during a 500 USDC volume candle has less information content than the same move during a 50,000 USDC candle.

    ## Candidate metadata

    - **proposed_name:** overnight_gap_fade
    - **edge_type:** structural
    - **time_window:** intraday
    - **market_types:** ['Any liquid binary market with sufficient overnight history', 'Crypto price markets (most active but also fastest to revert)', 'Political/electoral markets with stable underlying fundamentals']
    - **likely_inputs:** ['Hourly CLOB trade data: price, volume, timestamp', 'Per-market rolling 14-day volume profile (hourly buckets)', 'Current price vs 6h VWAP']

    ## Candidate logic

    ### Entry

    Alert when: (1) price moved >4% in a single 1-hour candle, (2) candle volume < 20th percentile of that hour-of-day's historical distribution for this market, (3) current price is >3% away from the 6h VWAP. Direction: fade the move (if price spiked up, alert YES→NO; if dropped, NO→YES).

    ### Exit / hold

    Close when price reverts within 2% of pre-move level OR at 18h elapsed from entry, whichever comes first. Hard stop if price extends a further 5% against the position.

    ## Expected failure modes

    - Overnight move is legitimate news (geopolitical event, regulatory ruling) — not a dislocation
- Crypto-adjacent markets may not revert; thin liquidity can persist for days
- VWAP anchor is stale for fast-moving political markets near resolution
- Low volume candle threshold is hard to calibrate across markets of very different total liquidity
- Multiple overnight dislocations in the same direction signal a real regime shift, not noise

    ## Validation plan

    Backtest on 90 days of CLOB data: for each qualifying alert, measure price at T+6h, T+12h, T+18h vs entry price. Calculate win rate and average reversion magnitude. Segment by market type (crypto vs political vs sports). Alert-only for first 30 signals; paper trade next 30 before going live. Require win rate >55% and ROI >0 before activating.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

# Strategy Proposal

    - **proposal_id:** PR-20260406-001
    - **date:** 2026-04-06
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    Multi-Outcome Implied Probability Oversum Decay

    ## Structured thesis

    Markets with 3+ mutually exclusive outcomes frequently have implied probabilities summing well above 100% due to the bid-ask spread baked into each outcome. When the oversum spikes (e.g., >115%) it often mean-reverts as arbitrageurs or informed traders correct the cheapest leg. We sell the most overpriced outcome (highest implied prob relative to a simple anchor like historical base rate or poll average) and buy the most underpriced one. Unlike outcome_count_oversum which just detects the condition, this strategy explicitly pairs a SHORT on the overpriced leg with a LONG on the underpriced leg, capturing the spread compression.

    ## Candidate metadata

    - **proposed_name:** multi_outcome_implied_prob
    - **edge_type:** logical_inconsistency
    - **time_window:** short
    - **market_types:** ['multi_outcome', 'categorical']
    - **likely_inputs:** ['gamma_api_prices', 'outcome_count', 'implied_prob_sum', 'historical_oversum_for_market', 'order_book_depth']

    ## Candidate logic

    ### Entry

    1. Scan active markets with >=3 mutually exclusive outcomes. 2. Compute implied probability sum across all outcomes. 3. If oversum > 112%, rank outcomes by (market_price - fair_share) where fair_share = 1/N as naive anchor. 4. Identify the most overpriced outcome (highest positive delta) and most underpriced (most negative delta). 5. Alert if the spread between them exceeds 8 cents AND each leg has >$500 daily volume. 6. Suggested position: sell overpriced outcome, buy underpriced outcome (dollar-neutral).

    ### Exit / hold

    Exit when oversum compresses below 105%, or after 48 hours, or if either leg moves 5c against us. Hard stop at 72 hours regardless.

    ## Expected failure modes

    - Oversum persists because all outcomes are genuinely uncertain and spread reflects real risk
- Thin books mean fills are much worse than mid-price signals suggest
- Correlated leg movement — both legs move against us if new info shifts distribution
- Resolution risk if market resolves while position is open on wrong side
- Gas/fee costs eat the small spread on low-stake trades

    ## Validation plan

    Backtest on 30 days of historical multi-outcome markets. Measure: (a) frequency of oversum >112%, (b) mean reversion speed, (c) simulated P&L assuming mid-price fills vs. realistic slippage. Alert-only for 2 weeks, track predicted spread compression vs actual. Minimum 10 alert events before considering live.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

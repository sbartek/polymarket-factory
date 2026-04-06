# Strategy Proposal

    - **proposal_id:** PR-20260404-004
    - **date:** 2026-04-04
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    New Market Anchor Drift

    ## Structured thesis

    Newly created Polymarket markets (first 24-48h) tend to open near 50c regardless of the true base rate, because early liquidity providers set naive initial prices and early bettors are attention-driven rather than informed. Markets with strong public base-rate information (e.g., 'Will [incumbent] win reelection?' when polls show 70%) should drift toward the base rate within days. Detect markets where the opening price diverges significantly from a simple base-rate estimate and alert on the expected drift direction. This builds on the base_rate_anchor concept but focuses specifically on the new-market window where mispricing is most acute.

    ## Candidate metadata

    - **proposed_name:** new_market_anchor_drift
    - **edge_type:** statistical_fade
    - **time_window:** short
    - **market_types:** ['elections', 'sports_season_outcomes', 'recurring_events', 'any_market_with_public_base_rate']
    - **likely_inputs:** ['polymarket API — filter markets created in last 48h', 'external base-rate sources (polls, betting odds, historical frequencies)', 'LLM to estimate base rate from market question + public data', 'market age and volume trajectory']

    ## Candidate logic

    ### Entry

    1. Scan for markets created within last 48h with volume < $10k. 2. Use LLM + structured data to estimate a base-rate probability. 3. Alert when |market_price - base_rate_estimate| > 15c AND confidence in base rate is high (source is polling average, historical frequency, or major sportsbook line). 4. Direction: if market < base_rate, signal YES; if market > base_rate, signal NO. 5. Require the base rate estimate to come from at least one concrete external source, not pure LLM judgment.

    ### Exit / hold

    Target exit when price moves halfway toward base rate estimate, or after 7 days (whichever first). Hard stop if price moves 10c further against the position (base rate estimate may be wrong).

    ## Expected failure modes

    - LLM base-rate estimates are poorly calibrated — garbage in, garbage out
- Market is new because it's genuinely uncertain, not because it's mispriced
- Early low-volume markets have wide spreads eating the edge
- Price anchored at 50c because informed traders haven't arrived yet — but they arrive on the wrong side
- Base rate from polls/odds already stale by the time market opens
- Selection bias: markets we can easily estimate a base rate for are also easy for other traders

    ## Validation plan

    1. ALERT-ONLY: log all new markets with volume < $10k and age < 48h, record opening price and LLM base-rate estimate with source. 2. Track price at 48h, 7d, and resolution. 3. Measure: (a) correlation between base-rate estimate and resolution outcome (calibration), (b) average drift toward base rate in first 7 days, (c) simulated P&L at $2 stakes with actual spread. 4. Require ≥20 tracked markets and Brier score < 0.25 on the base-rate estimates before considering paper trading. 5. Compare LLM estimates vs simple heuristic (e.g., just using betting odds) to check if LLM adds value.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

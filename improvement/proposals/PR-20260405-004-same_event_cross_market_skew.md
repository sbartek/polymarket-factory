# Strategy Proposal

    - **proposal_id:** PR-20260405-004
    - **date:** 2026-04-05
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    Same-Event Cross-Market Skew

    ## Structured thesis

    Polymarket often has multiple markets referencing the same underlying event with different framings (e.g. 'Will X happen by July?' at 35c vs 'Will X happen by end of year?' at 30c — logically inconsistent since the longer window must be >= the shorter). Similarly, a 'Will GDP growth exceed 3%?' market can be inconsistent with a multi-outcome GDP bracket market. These inconsistencies arise because different trader populations price each market independently. By systematically comparing related markets, we can identify and fade the mispriced side.

    ## Candidate metadata

    - **proposed_name:** same_event_cross_market_skew
    - **edge_type:** logical_inconsistency
    - **time_window:** medium
    - **market_types:** ['binary', 'multi-outcome']
    - **likely_inputs:** ['market_metadata_tags', 'market_descriptions', 'current_prices', 'event_groupings', 'resolution_dates']

    ## Candidate logic

    ### Entry

    1. Build a mapping of markets that reference the same underlying event using slug similarity, shared tags, and LLM-assisted grouping (batch, not real-time). 2. For each group, check logical price constraints: (a) longer-dated version must be >= shorter-dated for same outcome, (b) a specific threshold binary must be consistent with bracket market cumulative probabilities, (c) complementary markets (X wins vs X loses) must sum to ~$1 within spread. 3. Alert when constraint violation exceeds 5c after accounting for spread costs. 4. Suggested trade: buy the underpriced side.

    ### Exit / hold

    Exit when the skew narrows to <2c, or at resolution of the earlier-expiring market. Hard stop-loss at 10c adverse move.

    ## Expected failure modes

    - Resolution criteria may differ subtly between 'related' markets, making them not truly comparable
- LLM grouping may create false matches between superficially similar but distinct events
- Spread costs on both legs may eat the edge — need >5c gross skew to be viable
- Skew may persist indefinitely if both markets are illiquid
- One side may resolve ambiguously (void/refund) while the other doesn't

    ## Validation plan

    Alert-only for 3 weeks. Phase 1: validate the grouping — manually review first 30 market pairings for logical correctness. Phase 2: track skew alerts and whether they converge. Success criteria: >20 valid skew alerts, >65% converge within the monitoring period, median gross edge >6c. Only then consider paper-trading the clearest constraint violations (same-event different-timeframe pairs first, as these are hardest to dispute).

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

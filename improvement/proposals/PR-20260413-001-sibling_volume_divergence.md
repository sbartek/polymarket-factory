# Strategy Proposal

    - **proposal_id:** PR-20260413-001
    - **date:** 2026-04-13
    - **proposed_by:** strategy_factory_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    Fade low-volume price moves in multi-outcome markets

    ## Structured thesis

    In multi-outcome markets, when one sub-market's price moves significantly between snapshots but its volume is disproportionately low relative to sibling sub-markets, the move is likely noise from a thin fill rather than informed flow. Fade the outlier back toward its prior price. Statistical_fade and short window are the best-performing edge/window combos in the current book.

    ## Candidate metadata

    - **proposed_name:** sibling_volume_divergence
    - **edge_type:** statistical_fade
    - **time_window:** short
    - **market_types:** ['multi-outcome politics', 'multi-outcome sports', 'multi-outcome crypto targets']
    - **likely_inputs:** ['sub-market prices (current vs prior snapshot)', 'sub-market volumes', 'number of siblings', 'price change magnitude']

    ## Candidate logic

    ### Entry

    For each multi-outcome market with >=3 sub-markets: compute each sub-market's price delta and volume share (sub_vol / total_market_vol). Flag any sub-market where |price_delta| > 4¢ AND volume_share < 1/(2*num_siblings). Buy the opposite side of the move (e.g., if price jumped, buy NO; if price dropped, buy YES). Only act when the sub-market price is between 10¢-90¢ to avoid resolution-adjacent noise.

    ### Exit / hold

    Target: price reverts 50% of the flagged move. Stop: price continues 3¢ beyond the flagged move. Time stop: 48 hours.

    ## Expected failure modes

    - Thin move was actually informed — insider or early news leak
- Market is illiquid on both sides so fade order doesn't fill
- Snapshot frequency too low to catch the revert before it happens
- Multiple correlated sub-markets move together, triggering false signals
- Spread costs eat the small reversion profit
- Resolution occurs before reversion window closes

    ## Validation plan

    Alert-only for 2 weeks. Track: (1) how often the flagged price reverts >=50% within 48h, (2) median spread at signal time, (3) overlap with existing volume_divergence_stale signals. Need >=60% reversion rate and median spread <3¢ to promote to paper trading.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

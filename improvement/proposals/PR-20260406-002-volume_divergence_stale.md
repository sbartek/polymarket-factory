# Strategy Proposal

    - **proposal_id:** PR-20260406-002
    - **date:** 2026-04-06
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    Volume Divergence Stale Repricing

    ## Structured thesis

    When a market's trading volume spikes significantly (>3x its 7-day average) but the price barely moves (<2c), it often means new participants are absorbing existing liquidity at stale prices before the market adjusts. Conversely, when a highly correlated sibling market has already moved 5c+ on similar volume, the lagging market is likely mispriced. This combines volume anomaly detection with cross-market correlation to find stale prices with higher conviction than volume or staleness alone. The key insight from the evaluation data: pure stale_market had too few trades (3 closed) and pure volume signals (volume_spike_reversal) lack direction. Combining both signals should improve entry quality.

    ## Candidate metadata

    - **proposed_name:** volume_divergence_stale
    - **edge_type:** stale_repricing
    - **time_window:** short
    - **market_types:** ['binary', 'multi_outcome']
    - **likely_inputs:** ['gamma_api_prices', 'gamma_api_volume', 'rolling_7d_avg_volume', 'correlated_market_pairs', 'price_change_last_4h', 'order_book_depth']

    ## Candidate logic

    ### Entry

    1. Monitor all active markets for 4-hour volume >3x the 7-day rolling average. 2. Filter to markets where price moved <2c in the same window despite the volume spike. 3. Check if any pre-identified correlated market moved >5c in the same 4h window. 4. If correlated market moved AND this market is stale: alert to buy/sell in the direction of the correlated market's move. 5. Require minimum $200 volume in the stale market to ensure fillability. 6. Position size: $2-5 per alert (micro stakes).

    ### Exit / hold

    Exit when price moves >3c in our direction (partial convergence), or after 24 hours, or if the correlated market reverses its move. Trailing stop at 4c loss from entry.

    ## Expected failure modes

    - Volume spike is wash trading or bot activity with no information content
- Correlated market moved on market-specific news, not shared factor
- Stale market has a structural reason for not moving (e.g., locked liquidity, different resolution date)
- Correlation breaks down — historical correlation was spurious
- 24h exit window is too short for convergence on low-liquidity markets
- Multiple signals fire simultaneously, concentrating risk

    ## Validation plan

    Build correlation matrix for top 100 active markets over 30 days. Identify pairs with >0.6 price correlation. Backtest volume-divergence signals on these pairs: measure how often the stale market converges within 24h and by how much. Alert-only for 3 weeks targeting 15+ alerts. Track hit rate (did stale market move in predicted direction?) and magnitude.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

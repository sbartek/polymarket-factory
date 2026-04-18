# Strategy Proposal

    - **proposal_id:** PR-20260418-002
    - **date:** 2026-04-18
    - **proposed_by:** strategy_factory_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    Follow disproportionate volume in multi-outcome markets

    ## Structured thesis

    In multi-outcome markets (e.g., 'Who will be next X?' with 5+ outcomes), retail flow spreads evenly across narratively appealing names while informed flow concentrates on the likely winner. When one outcome's share of total market volume significantly exceeds its share of total market price (e.g., outcome has 40% of volume but only 20% of price), it signals disproportionate informed buying. This is distinct from oversum arbitrage (spread_arb_v2 exploits prices summing above 100%) and from correlated_laggard (which pairs separate markets). This strategy operates within a single multi-outcome market, using the volume-vs-price skew across sub-markets as the signal.

    ## Candidate metadata

    - **proposed_name:** outcome_volume_concentration
    - **edge_type:** structural
    - **time_window:** short
    - **market_types:** ['multi_outcome', 'categorical']
    - **likely_inputs:** ['parent_market_slug', 'sub_market_prices', 'sub_market_volumes', 'sub_market_count', 'end_date']

    ## Candidate logic

    ### Entry

    1. Filter parent markets with 4+ sub-outcomes. 2. For each sub-outcome, compute volume_share = outcome_volume / total_volume and price_share = outcome_price / sum(prices). 3. Compute concentration_ratio = volume_share / price_share. 4. If any outcome has concentration_ratio > 2.0 and price < 40%, BUY that outcome. 5. Require total market volume > $2000 (enough flow to be meaningful). 6. Require endDate within 30 days (avoid long-dated markets where volume patterns are noisy). Alert-only initially.

    ### Exit / hold

    Hold to resolution or until price rises 15+ cents (take profit on repricing). Stop-loss if concentration_ratio drops below 1.0 (informed flow reversed or was noise).

    ## Expected failure modes

    - Volume spikes from a single large retail whale, not informed flow
- Market makers hedging creates volume without directional signal
- Volume data from snapshot may miss intraday wash trading
- Low-price outcomes have inflated concentration ratios from tiny absolute volumes
- Signal decays quickly — by the time snapshot runs, price may have already adjusted
- Multi-outcome markets often have poor liquidity on individual outcomes

    ## Validation plan

    Compute concentration_ratio on all resolved multi-outcome markets from past 60 days using historical snapshots. Check if outcomes with ratio > 2.0 resolved Yes more often than their price implied. Target: implied edge > 10% after fees. Start alert-only, manually verify 5-10 signals before enabling paper trading.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

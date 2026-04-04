# Strategy Proposal

    - **proposal_id:** PR-20260404-003
    - **date:** 2026-04-04
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** approved

    ## Plain-language idea

    Conditional Probability Mispricing

    ## Structured thesis

    When market A is a necessary condition for market B (e.g., 'Team X wins semifinal' is required for 'Team X wins final'), B's price should never exceed A's price. In practice, attention-driven flows on the 'sexier' downstream market can push B above A, creating a pure logical arbitrage. Buy A, sell B when B > A by more than fee+spread threshold. This is a tighter, more auditable version of correlated_pairs — instead of statistical correlation, we enforce a strict logical implication.

    ## Candidate metadata

    - **proposed_name:** conditional_probability_mispricing
    - **edge_type:** logical_inconsistency
    - **time_window:** medium
    - **market_types:** ['sports_tournaments', 'political_primaries', 'sequential_events', 'conditional_markets']
    - **likely_inputs:** ['polymarket API for related market groups', 'manual or LLM-assisted tagging of prerequisite relationships', 'orderbook spread and depth on both legs']

    ## Candidate logic

    ### Entry

    1. Maintain a registry of (prerequisite_market, downstream_market) pairs where downstream logically requires prerequisite. 2. Alert when P(downstream) > P(prerequisite) - fee_threshold (e.g., 2c after fees). 3. Require minimum $500 liquidity within 2c of mid on both sides. 4. Flag direction: BUY prerequisite YES, SELL downstream YES (or equivalent NO positions).

    ### Exit / hold

    Exit when spread reverts to ≤1c or either market resolves. If prerequisite resolves NO, downstream must also resolve NO — collect on both. If prerequisite resolves YES, hold downstream position to resolution.

    ## Expected failure modes

    - Prerequisite relationship misidentified — downstream doesn't actually require prerequisite
- Markets resolve on different timelines, tying up capital
- Thin liquidity means you can't get both legs filled at the mispriced spread
- Fee structure eats the small edge on tight mispricings
- Market rules or resolution criteria differ subtly from the logical model

    ## Validation plan

    1. ALERT-ONLY for 2 weeks: scan tournament/sequential market groups and log all detected mispricings with timestamps and magnitudes. 2. Track how often the mispricing reverts within 24h vs persists. 3. Simulate P&L assuming $2 per leg with actual orderbook fills. 4. Require ≥10 detected mispricings and ≥60% reversion rate before considering paper trading. 5. Manually verify every prerequisite relationship before trusting it.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

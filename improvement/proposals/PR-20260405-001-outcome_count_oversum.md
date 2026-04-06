# Strategy Proposal

    - **proposal_id:** PR-20260405-001
    - **date:** 2026-04-05
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    Multi-Outcome Markets with >100% Sum of Implied Probabilities

    ## Structured thesis

    Markets with 3+ outcomes (e.g. 'Who will win X?' with named candidates) frequently have implied probabilities summing well above 100% due to wide spreads and low liquidity on individual outcomes. When the oversum exceeds a threshold (e.g. 115%), the least-likely outcomes are systematically overpriced — their NO sides offer positive EV. This is a generalization of mutually_exclusive_oversum but focuses specifically on identifying which leg(s) to fade rather than just flagging the oversum.

    ## Candidate metadata

    - **proposed_name:** outcome_count_oversum
    - **edge_type:** logical_inconsistency
    - **time_window:** medium
    - **market_types:** ['multi_outcome', 'winner_markets', 'nomination_markets']
    - **likely_inputs:** ['clob_book_snapshots', 'outcome_count', 'best_bid_ask_per_outcome', 'market_volume', 'market_end_date']

    ## Candidate logic

    ### Entry

    1. Scan multi-outcome markets (3+ outcomes). 2. Compute sum of best-ask prices across all outcomes. 3. If oversum > 115%, rank outcomes by implied probability. 4. For outcomes with implied prob < 10% (ask price < 0.10), check if NO side bid > 0.90 with reasonable depth (>$50). 5. Alert on NO positions for bottom-ranked outcomes where the oversum alone covers expected slippage + fees. 6. Require at least $50 resting bid depth on the NO side to ensure fillability.

    ### Exit / hold

    Hold NO positions to resolution. If outcome's ask price drops below 0.03 (market converging toward correct pricing), consider early exit by selling NO at profit. Exit early if oversum collapses below 105% (edge gone).

    ## Expected failure modes

    - Oversum persists because spreads are wide and unfillable — depth is illusory
- Black swan: a 5% outcome actually wins, NO position loses big
- Market resolves ambiguously or gets voided, locking up capital
- Fees + slippage eat the thin edge from oversum
- Correlated outcomes (e.g. two candidates from same party) make simple oversum math misleading
- Low volume means positions take days to fill at desired price

    ## Validation plan

    Alert-only for 2 weeks. Track: (a) how often oversum >115% occurs across active multi-outcome markets, (b) what fill rate would be achievable at alerted prices, (c) simulated P&L assuming NO at best bid on bottom-3 outcomes. Kill if fewer than 5 alerts/week or simulated ROI < 0 after fees.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

# Strategy Proposal

    - **proposal_id:** PR-20260413-002
    - **date:** 2026-04-13
    - **proposed_by:** strategy_factory_cycle
    - **status:** archived

    ## Plain-language idea

    Buy high-confidence leaders approaching expiry

    ## Structured thesis

    Markets within 3-7 days of endDate where the leading outcome is priced 75-92¢ carry a 'resolution uncertainty discount' — participants are slow to price in near-certainty because selling NO at 8-25¢ feels risky close to expiry. As the clock ticks down, these prices converge toward 95-99¢. This is essentially a time-decay trade: harvesting the last few cents of repricing as uncertainty collapses. Stale_repricing has positive ROI (+19.3%) in the current book despite small sample.

    ## Candidate metadata

    - **proposed_name:** expiry_convergence_buy
    - **edge_type:** stale_repricing
    - **time_window:** short
    - **market_types:** ['binary yes/no', 'multi-outcome with clear leader', 'date-based resolution']
    - **likely_inputs:** ['endDate', 'current price of leading outcome', 'days to expiry', 'volume in last snapshot', 'price stability (variance across recent snapshots)']

    ## Candidate logic

    ### Entry

    Select markets where: days_to_expiry between 3-7, leading outcome price between 75¢-92¢, the leader has been the leader for >=3 consecutive snapshots (stable, not a fresh spike), and 24h volume > $500 (enough liquidity to exit). Buy YES on the leader. Skip markets with 'conditional' in the title or where resolution depends on an external event that hasn't occurred yet (detectable via title keywords like 'if', 'conditional').

    ### Exit / hold

    Target: price reaches 95¢ or higher. Stop: price drops below 70¢ (thesis broken — real uncertainty emerged). Time stop: hold to expiry minus 6 hours, then close if not resolved.

    ## Expected failure modes

    - Late-breaking news reverses the leader (e.g., candidate drops out)
- Market resolves N/A or gets voided near expiry
- Liquidity dries up in final days — can't exit at fair price
- The 75-92¢ price correctly reflects genuine uncertainty, not stale repricing
- Resolution mechanism is slow, causing the market to sit at 92¢ past expiry

    ## Validation plan

    Alert-only for 3 weeks. Track: (1) what price the leader reaches by expiry, (2) how many signals reverse below 70¢, (3) average spread at entry. Need >=70% of signals to reach 95¢+ and <15% to hit the 70¢ stop to promote to paper trading.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

# Strategy Proposal

    - **proposal_id:** PR-20260403-004
    - **date:** 2026-04-03
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** archived
    - **deferred_reason:** Overlaps with correlated_laggard (promoted 2026-04-04). Evaluate correlated_laggard results first before adding a second related-market strategy.

    ## Plain-language idea

    Resolved Sibling Market Lag

    ## Structured thesis

    When Market A resolves (or crosses >90% certainty), a logically dependent Market B often takes 1–12 hours to reprice. Example: 'Will X win the primary?' resolves YES → 'Will X win the general?' should immediately reprice upward based on conditional probability, but market participants are slow. Unlike correlated_laggard (which looks for correlated price drift), this strategy specifically targets the resolution event as a trigger and exploits the 1–12h window before the sibling catches up. Concrete, auditable: sibling relationship is declared at signal-time via keyword/tag overlap plus price correlation check.

    ## Candidate metadata

    - **proposed_name:** resolved_sibling_lag
    - **edge_type:** resolution_lag
    - **time_window:** short
    - **market_types:** ['political primaries → general elections', 'sports round-by-round elimination brackets', 'multi-stage geopolitical events', 'award season (nomination → win)']
    - **likely_inputs:** ['recently_resolved_markets (last 24h)', 'candidate_sibling_markets (tag overlap + keyword match)', 'pre_resolution_price of sibling', 'current_price of sibling', 'time_since_resolution', 'historical_conditional_base_rate (optional)']

    ## Candidate logic

    ### Entry

    Parent market resolves YES or NO (or crosses 0.92). Find sibling markets sharing ≥2 tags or ≥3 keyword tokens. Compute expected price shift using base-rate conditional (e.g., primary winner historically wins general ~65%). If sibling price has moved <40% of expected shift within 2h of parent resolution, enter in the direction of expected shift. Cap position at $5 alert-only initially.

    ### Exit / hold

    Exit when sibling price moves ≥70% of expected shift, OR at 24h timeout, OR if a contradicting news event fires.

    ## Expected failure modes

    - Sibling market is not actually logically dependent (false keyword match)
- Base-rate conditional is wrong for this specific context
- Resolution of parent was contested or reversed
- Sibling market has very low liquidity — fills move price against entry
- Other informed traders already arbed the gap before signal fires
- Parent resolves ambiguously (N/A) — sibling price move is unpredictable

    ## Validation plan

    Alert-only for 6 weeks. Log each triggered signal: parent market, sibling market, expected shift direction, actual sibling price at T+2h, T+6h, T+24h. Success criterion: sibling moves in predicted direction by T+24h in >60% of cases AND mean absolute reversion magnitude > 0.08. Sanity-check sibling identification precision — flag any false-match rate >25%.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

# Strategy Proposal

    - **proposal_id:** PR-20260410-004
    - **date:** 2026-04-10
    - **proposed_by:** strategy_factory_cycle
    - **status:** pending_benchmark_review

    ## Plain-language idea

    Resolution-hunter conservative variation with stricter certainty gating

    ## Structured thesis

    The current resolution_hunter may be too permissive; a stricter version could surface fewer but cleaner near-resolution opportunities where the market lags obvious settlement direction.

    ## Candidate metadata

    - **proposed_name:** resolution_hunter_conservative_20260410_gen
    - **edge_type:** resolution_lag
    - **time_window:** short
    - **market_types:** near-resolution event markets
    - **likely_inputs:** closed/open market snapshot, title filters, simple certainty screens

    ## Candidate logic

    ### Entry

    Require stronger evidence and narrower market states before raising an alert; prefer cases where ambiguity appears materially lower than price implies.

    ### Exit / hold

    Hold logic remains resolution-focused; promotion only if alerts are materially cleaner than the base strategy.

    ## Expected failure modes

    - too few opportunities
- false sense of certainty
- headline ambiguity near resolution
- better precision but negligible capacity

    ## Validation plan

    Run side-by-side with resolution_hunter as alert-only for one month; compare alert precision and Phase A execution realism.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

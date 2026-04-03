# Strategy Proposal

    - **proposal_id:** PR-20260403-002
    - **date:** 2026-04-03
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** approved

    ## Plain-language idea

    Mutually Exclusive Market Probability Oversum

    ## Structured thesis

    When Polymarket hosts multiple mutually exclusive outcome markets for the same event (e.g. 'Will X win?' for each candidate in a race), the sum of YES prices must equal ~1.0 after fees. In practice the sum often exceeds 1.05–1.15 due to stale prices, bettors treating each market independently, or liquidity fragmentation. Buying the cheapest NO (i.e. shorting the overpriced candidate) relative to the sum exploits a provable mathematical inconsistency rather than a probabilistic opinion.

    ## Candidate metadata

    - **proposed_name:** mutually_exclusive_oversum
    - **edge_type:** logical_inconsistency
    - **time_window:** short
    - **market_types:** ['multi-candidate election markets (presidential, mayoral, party leader)', 'award winner markets (Oscar, Nobel) with 4+ candidates', 'sports tournament outright winner markets with bracket structure', "'Which team will finish X place?' league markets"]
    - **likely_inputs:** ['list of sibling markets for the same event (scraped via Polymarket tags/slug patterns)', 'YES price for each candidate', 'sum of all YES prices', 'individual market volumes and spreads', 'resolution date and current date']

    ## Candidate logic

    ### Entry

    Alert when: (1) sum of YES prices across all mutually exclusive outcomes > 1.08 (8% oversum, covering ~2% fees per leg), (2) all individual markets have volume > $500, (3) at least 7 days to resolution. Buy NO on the most overpriced candidate (highest YES price relative to its fair share of the remaining probability). Single-leg entry — do not buy multiple NOs simultaneously unless capital allows hedging all legs.

    ### Exit / hold

    Close when sum of YES prices drops below 1.03, or when the overpriced candidate's YES price drops by >40% from entry. Hard exit 48h before resolution to avoid last-mile uncertainty. Do not hold through resolution — this is a repricing trade, not an outcome bet.

    ## Expected failure modes

    - A new candidate enters the race after entry, changing the mutual exclusivity structure
- Market resolves as N/A or ambiguous (Polymarket cancellations have happened)
- Thin liquidity prevents meaningful position size — alerts fire but fills are < $5
- Oversum persists or widens — not all mispricings revert before resolution
- Sibling market detection relies on tagging that Polymarket applies inconsistently
- Dark liquidity / large hidden bets resolve the oversum before entry is filled

    ## Validation plan

    Build sibling-market grouping logic using Polymarket tag/event slug. Audit 30 past resolved multi-candidate elections: measure oversum frequency, magnitude, and how long before resolution it corrected. If >60% of oversums > 1.08 corrected within 7 days, proceed to ALERT-ONLY. Track 20 real alerts for fillability and revert timing before enabling live trades. Size cap: $25/position until 30+ closed trades logged.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Auto-approved under the one-month aggressive strategy experiment.

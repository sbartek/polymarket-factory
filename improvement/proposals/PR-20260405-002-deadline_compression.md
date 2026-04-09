# Strategy Proposal

    - **proposal_id:** PR-20260405-002
    - **date:** 2026-04-05
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** archived

    ## Plain-language idea

    Fade Long-Shot YES Positions as Market Deadline Approaches

    ## Structured thesis

    Binary markets with end dates within 48-72 hours where YES is priced 5-20% represent events that are unlikely to happen in the remaining time. Retail participants and bot noise keep these prices elevated above fair value because (a) there is no cost-of-carry forcing prices down and (b) hopeful holders don't actively sell. Buying NO at 80-95c in these near-expiry markets captures a small but frequent edge as time decay isn't priced efficiently on Polymarket the way it is in options markets.

    ## Candidate metadata

    - **proposed_name:** deadline_compression
    - **edge_type:** statistical_fade
    - **time_window:** short
    - **market_types:** ['binary', 'time_bounded', 'event_outcome']
    - **likely_inputs:** ['market_end_date', 'current_yes_price', 'market_volume_24h', 'price_history_7d', 'order_book_depth']

    ## Candidate logic

    ### Entry

    1. Filter binary markets resolving in 24-72 hours. 2. Select markets where YES ask is 0.05-0.20 and has been in this range (no upward trend) for >48 hours. 3. Exclude markets where the underlying event could plausibly happen suddenly (e.g. breaking news categories — filter by market tags). 4. Require NO bid depth > $100 at 0.85+. 5. Alert to buy NO at best ask (0.80-0.95). 6. Prefer markets with >$10k total volume (establishes that price discovery has occurred).

    ### Exit / hold

    Hold to resolution (primary). If YES price spikes above 0.30 (new information suggests event may happen), exit NO immediately to cut losses. Target: collect full NO payout at resolution.

    ## Expected failure modes

    - Late-breaking event causes YES to spike — NO position loses 80-95c per share
- Market resolution delayed past end date, tying up capital
- Edge is real but tiny (5-15% return on 85-95c cost) — not worth capital allocation
- Filtering out 'sudden event' markets is hard to automate reliably
- Many near-expiry low-YES markets have zero liquidity on the NO side
- Resolution criteria ambiguity causes unexpected YES resolution

    ## Validation plan

    Alert-only for 3 weeks. Track all binary markets in final 72 hours where YES is 5-20%. Record: (a) final resolution outcome, (b) theoretical fill price for NO, (c) simulated P&L. Expect >85% win rate but small per-trade profit. Kill if win rate < 80% or if average loss on losers exceeds 6x average win (risk/reward too skewed).

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

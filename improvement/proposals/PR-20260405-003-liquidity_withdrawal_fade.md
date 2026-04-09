# Strategy Proposal

    - **proposal_id:** PR-20260405-003
    - **date:** 2026-04-05
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** archived

    ## Plain-language idea

    Liquidity Withdrawal Fade

    ## Structured thesis

    When a market's order book thins significantly (e.g. top-of-book depth drops >60% vs 24h average), the last traded price often overshoots fair value because a single moderate-sized order can move the price disproportionately. By tracking depth snapshots and flagging markets where liquidity has suddenly dried up, we can identify prices that have drifted from fundamental value and fade the move once liquidity returns. This exploits the structural fact that Polymarket's CLOB has no market makers with obligations — LPs can pull quotes freely, creating temporary vacuums.

    ## Candidate metadata

    - **proposed_name:** liquidity_withdrawal_fade
    - **edge_type:** structural
    - **time_window:** short
    - **market_types:** ['binary', 'multi-outcome']
    - **likely_inputs:** ['order_book_depth_snapshots', 'last_trade_price', '24h_vwap', 'spread_history', 'volume_profile']

    ## Candidate logic

    ### Entry

    1. Poll order book depth every 15 min for active markets. 2. Flag when top-3-level depth on either side drops below 40% of its trailing 24h median AND the mid price has moved >4c from 24h VWAP. 3. Alert to fade the price move (buy if price dropped, sell if price spiked) with a limit order at the 24h VWAP. 4. Only act on markets with >$50k total volume (enough history for depth baseline).

    ### Exit / hold

    Exit when price reverts to within 1.5c of 24h VWAP, or after 48h if no reversion (stop-loss at 8c adverse move from entry).

    ## Expected failure modes

    - Liquidity withdrawal is informed — LPs pull because they know something we don't
- Depth data from API may be stale or incomplete vs actual CLOB state
- Reversion may not happen if the move reflects genuine new information
- Thin books mean our own order could be a significant fraction of depth, limiting capacity
- Polling frequency may miss rapid liquidity changes

    ## Validation plan

    Run alert-only for 2 weeks. Track: (a) how often flagged price dislocations revert within 48h, (b) magnitude of reversion vs initial displacement, (c) whether depth recovery precedes or follows price reversion. Need >15 alerts with >60% reversion rate before considering paper-trading. Cross-check against news feeds to filter out informed liquidity pulls.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

# Strategy Proposal

    - **proposal_id:** PR-20260403-001
    - **date:** 2026-04-03
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** archived

    ## Plain-language idea

    Thin Market Liquidity Impact Fade

    ## Structured thesis

    On low-liquidity Polymarket markets, a single large order can move the price 15–30% without any information content. Once the order is absorbed and the book refills, the price tends to revert. Fading this transient price impact — not the underlying probability — captures a structural inefficiency. Unlike stale_market (which triggers on time-since-update), this strategy triggers on sudden price jumps in thin books, making it event-driven and faster to act.

    ## Candidate metadata

    - **proposed_name:** thin_market_impact_fade
    - **edge_type:** structural
    - **time_window:** super_short
    - **market_types:** ['low-volume binary markets (< $5k total volume)', 'long-dated markets with infrequent trading', 'niche sports, local politics, celebrity outcomes']
    - **likely_inputs:** ['orderbook depth (best bid/ask, top-5 levels)', 'recent trade history (last 10 trades, timestamps)', '24h volume', 'price N minutes ago vs price now', 'implied move size relative to book depth']

    ## Candidate logic

    ### Entry

    Alert when: (1) price moved >15% in last 30 minutes, (2) 24h volume < $3k, (3) the move is attributable to ≤3 trades (thin book swept), (4) current spread is still abnormally wide. Fade direction: if price spiked up, sell YES (or buy NO); if spiked down, buy YES.

    ### Exit / hold

    Close when price reverts to within 5% of pre-move level OR after 4 hours, whichever comes first. Hard stop: exit if price moves a further 10% against position (momentum continuation signal).

    ## Expected failure modes

    - The large order was informed — price spike is the new fair value
- Market stays illiquid and spread prevents profitable exit
- Resolution event occurs during revert window, locking in loss
- Polymarket API doesn't expose per-trade granularity needed for trigger detection
- Slippage on entry/exit in thin book eats the entire expected revert

    ## Validation plan

    Backtest on historical CLOB data: identify all markets with 24h volume < $3k that experienced a ≥15% price move within 30 min. Measure mean reversion within 4h. Target: >55% of spikes partially revert within 2h. Run ALERT-ONLY for 3 weeks before committing capital. Minimum 20 triggered alerts needed before live trading evaluation.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Auto-approved under the one-month aggressive strategy experiment.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

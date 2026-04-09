# Strategy Proposal

    - **proposal_id:** PR-20260403-003
    - **date:** 2026-04-03
    - **proposed_by:** aggressive_strategy_cycle
    - **status:** archived
    - **deferred_reason:** Needs CLOB trade-level data (per-trade volume/price) not available from Gamma snapshot API. Revisit if we add a trade data pipeline.

    ## Plain-language idea

    Volume Spike Reversal

    ## Structured thesis

    A sudden volume spike (5x+ 7-day average in a 4h window) paired with a price move >15% usually reflects a single large order or coordinated retail FOMO hitting a thin book. The informed-money price hasn't changed — the book just got crossed. Once the spike subsides and the book refills, price reverts. This differs from thin_market_impact_fade: that strategy fires at the moment of impact; this one waits for the spike to exhaust, then fades the residual overshoot.

    ## Candidate metadata

    - **proposed_name:** volume_spike_reversal
    - **edge_type:** statistical_fade
    - **time_window:** intraday
    - **market_types:** ['political', 'sports', 'crypto events', 'any binary with moderate liquidity']
    - **likely_inputs:** ['polymarket_trades volume rolling 4h vs 7-day baseline', 'price_before_spike (snapshot at spike start)', 'current_price', 'time_since_spike_peak', 'spread width (proxy for book depth)']

    ## Candidate logic

    ### Entry

    Volume in last 4h > 5x 7-day daily average AND abs(current_price - price_4h_ago) > 0.15 AND volume rate is now declining (peak passed). Enter fade position toward pre-spike anchor price. Skip if there is a confirmed news event explaining the move (cross-check ev_news signal).

    ### Exit / hold

    Exit when price reverts 60% of the spike move, OR at 6h timeout, OR if volume spikes again in same direction (invalidates thesis).

    ## Expected failure modes

    - Volume spike is informed (leak, insider) — price does not revert
- Spike caused by genuine news not captured by ev_news filter
- Thin book means fills are partial or at poor prices
- Spike occurs near resolution date — price correctly moves toward 0/1
- Multiple consecutive spikes in same direction; averaging into a trend

    ## Validation plan

    Run in alert-only mode for 30 days. Log every triggered signal with: spike magnitude, price move, time-to-revert, whether a news event was later identified. Target: >50% of signals show >50% reversion within 6h. Kill if reversion rate <35% or if news-event contamination >40% of signals.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

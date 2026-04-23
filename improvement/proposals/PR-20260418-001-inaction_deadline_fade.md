# Strategy Proposal

    - **proposal_id:** PR-20260418-001
    - **date:** 2026-04-18
    - **proposed_by:** strategy_factory_cycle
    - **status:** archived

    ## Plain-language idea

    Fade Yes on deadline-bound inaction markets

    ## Structured thesis

    Many Polymarket questions ask 'Will X happen by [date]?' where X requires active government/corporate action (legislation, executive orders, appointments, product launches). The base rate for such actions completing on time is low — bureaucracies are slow, announcements slip, and the market narrative inflates Yes prices via availability bias. When a deadline-bound market has Yes priced above 20% but the endDate is within 14 days and there is no sub-market price movement suggesting imminent resolution, selling Yes (buying No) captures time decay plus inaction base rates. This is distinct from expiry_convergence (which buys leaders) and stale_market (which uses LLM news judgment) — this is a pure statistical prior on governmental/institutional inaction applied to deadline markets.

    ## Candidate metadata

    - **proposed_name:** inaction_deadline_fade
    - **edge_type:** statistical_fade
    - **time_window:** medium
    - **market_types:** ['binary_deadline', 'will_X_by_date']
    - **likely_inputs:** ['market_title', 'market_price', 'end_date', 'volume_24h', 'market_category']

    ## Candidate logic

    ### Entry

    1. Filter markets whose title matches patterns like 'Will * by *', 'before *', '* deadline'. 2. Require endDate within 7-21 days. 3. Require Yes price between 15-45% (not already priced for failure, but overvalued vs inaction base rate). 4. Exclude sports/weather (outcomes not driven by institutional action). 5. Require 24h volume > $500 (fillable). 6. BUY NO at current price. Alert-only initially.

    ### Exit / hold

    Hold to resolution. If Yes price drops below 8%, consider early exit to free capital. Stop-loss if Yes price rises above 60% (indicates genuine momentum toward action).

    ## Expected failure modes

    - Title pattern matching misclassifies sports/weather markets as institutional-action markets
- Some institutions do act on time — blanket No bias loses on those
- Thin No-side liquidity means fills are at worse prices than displayed
- Market makers already price inaction correctly on high-profile markets
- Regulatory/political surprises can cause sudden Yes spikes with no exit
- Small edge gets eaten by Polymarket fees on low-conviction trades

    ## Validation plan

    Backtest on resolved 'Will X by date' markets from past 90 days: compute what a systematic No entry at 14 days out would have returned. Target: >55% win rate and positive ROI after fees. Start alert-only with $1 stakes on 10 markets.

    ## Open questions for review

    - aggressive auto-generated candidate

    ## Approval note

    Generated automatically under the aggressive strategy experiment.
    Retention now depends on replay-benchmark evidence or explicit review.

## Benchmark gate note

Archived by benchmark gate: no generated benchmark evidence after 3 days

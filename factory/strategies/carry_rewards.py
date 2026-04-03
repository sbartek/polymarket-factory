"""
Strategy: carry_rewards
Hypothesis: Binary Polymarket markets offer ~4% APY via Polymarket Holding Rewards
            when you hold a market-neutral full set (YES + NO tokens). Regardless of
            outcome, a full set always resolves to exactly $1.00, so the only return
            is the holding yield.
Method: Scan binary markets with sufficient duration and volume. Rank by carry yield
        (= days_remaining / 365 * 4%). Alert-only — no directional view, signals are
        full-set purchase candidates for live deployment.

Paper-trading note: alert_only because resolution P&L is always ~$0 (neutral by
construction), and Holding Rewards accrue off-chain and can't be tracked by the
paper broker. Real yield only materialises in live trading.
"""
from datetime import date

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

HOLDING_REWARDS_APY = 0.04    # ~4% per year from Polymarket Holding Rewards
MIN_CARRY_PP = 3.0            # min expected yield in pp (~27 days at 4% APY)
MIN_VOLUME = 20_000           # 24h volume floor — need enough liquidity to enter/exit
MIN_DAYS = 25                 # too short → negligible carry
MAX_DAYS = 180                # too long → capital tied up, higher tail risk
MAX_SIGNALS_PER_RUN = 4
MIN_YES_PRICE = 0.10          # filter out near-certain markets (not interesting for carry)
MAX_YES_PRICE = 0.90


def _days_to_close(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        return (date.fromisoformat(end_date[:10]) - date.today()).days
    except ValueError:
        return None


def _is_binary(ev: dict) -> bool:
    """True if this event has exactly one active YES/NO market (not a multi-outcome event)."""
    active = [m for m in ev.get("markets", []) if not m.get("closed")]
    return len(active) == 1


class CarryRewardsStrategy(Strategy):
    name = "carry_rewards"
    edge_type = "structural"
    time_window = "long"
    target_hold_min_days = MIN_DAYS
    target_hold_max_days = MAX_DAYS
    scan_frequency = "daily"
    max_position_usdc = 10.0
    min_ev_pp = MIN_CARRY_PP
    alert_only = True
    trading_enabled = False

    def scan(self, markets: list[dict]) -> list[Signal]:
        candidates = []
        for ev in markets:
            if not _is_binary(ev):
                continue
            vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
            if vol < MIN_VOLUME:
                continue
            days = _days_to_close(ev.get("endDate"))
            if days is None or not (MIN_DAYS <= days <= MAX_DAYS):
                continue
            yes_price = get_yes_price(ev)
            if yes_price is None or not (MIN_YES_PRICE <= yes_price <= MAX_YES_PRICE):
                continue
            carry_pp = round((days / 365) * HOLDING_REWARDS_APY * 100, 1)
            if carry_pp < MIN_CARRY_PP:
                continue
            candidates.append((ev, days, carry_pp, vol, yes_price))

        # rank by carry yield (higher days = more yield), break ties by volume
        candidates.sort(key=lambda x: (x[2], x[3]), reverse=True)
        selected = candidates[:MAX_SIGNALS_PER_RUN]

        signals: list[Signal] = []
        for ev, days, carry_pp, vol, yes_price in selected:
            slug = ev.get("slug", "") or str(ev.get("id", ""))
            title = (ev.get("title") or "?")[:100]
            print(f"  [{self.name}] {title[:55]} | days={days} carry={carry_pp:.1f}pp vol=${vol:,.0f}")
            signals.append(Signal(
                strategy=self.name,
                market_id=slug,
                market_title=title,
                outcome="YES",
                market_price=round(yes_price, 4),
                p_hat=round(yes_price, 4),  # neutral — no directional view
                ev_pp=carry_pp,
                confidence="high",
                closes=(ev.get("endDate") or "")[:10],
                url=event_url(ev),
                rationale=f"carry:full-set,days={days},apy={HOLDING_REWARDS_APY*100:.0f}%,yield={carry_pp:.1f}pp",
            ))

        print(f"  [{self.name}] {len(signals)} carry signals ({len(candidates)} candidates, alert-only)")
        return signals

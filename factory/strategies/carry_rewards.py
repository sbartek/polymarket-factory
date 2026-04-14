"""
Strategy: carry_rewards
Hypothesis: Polymarket pays ~4% APY Holding Rewards on select long-dated political
            and geopolitical markets. Buying a full set (YES + NO) on these markets
            earns the carry with zero directional risk (full set always resolves to $1).

Note: Holding Rewards only apply to eligible markets (2028 presidential race,
2026 midterms, leadership outcomes in major countries, etc.) — NOT all markets.
The strategy filters for these by checking category tags and long time horizons.

Demoted to paper-only (2026-04-14): zero signals historically because the eligible
markets are mostly multi-outcome (not binary). Relaxed filters to observe signal flow.
"""
from datetime import date

from ..feed import event_url, get_yes_price
from ..models import Signal
from .base import Strategy

HOLDING_REWARDS_APY = 0.04    # ~4% per year from Polymarket Holding Rewards
MIN_CARRY_PP = 0.5            # relaxed to observe signal flow
MIN_VOLUME = 10_000           # lowered — eligible long-dated markets may have less daily volume
MIN_DAYS = 30                 # eligible markets are long-dated
MAX_DAYS = 900                # some eligible markets are 2+ years out (e.g. 2028 presidential)
MAX_SIGNALS_PER_RUN = 4
MIN_YES_PRICE = 0.05          # wider range for long-dated markets
MAX_YES_PRICE = 0.95

# Keywords in titles/categories that suggest Holding Rewards eligibility
ELIGIBLE_KEYWORDS = [
    "president", "election", "midterm", "congress", "senate", "governor",
    "prime minister", "leadership", "regime", "head of state",
]


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


def _looks_eligible(ev: dict) -> bool:
    """Heuristic: does this market look like a Holding Rewards eligible market?"""
    title = (ev.get("title") or "").lower()
    category = (ev.get("category") or "").lower()
    raw_tags = ev.get("tags") or []
    tags = " ".join(
        str(t).lower() if isinstance(t, str) else str(t.get("label", "")).lower()
        for t in raw_tags
    )
    text = f"{title} {category} {tags}"
    return any(kw in text for kw in ELIGIBLE_KEYWORDS)


class CarryRewardsStrategy(Strategy):
    name = "carry_rewards"
    mode = "paper"
    edge_type = "structural"
    time_window = "long"
    target_hold_min_days = MIN_DAYS
    target_hold_max_days = MAX_DAYS
    scan_frequency = "daily"
    max_position_usdc = 10.0
    min_ev_pp = MIN_CARRY_PP
    alert_only = False
    trading_enabled = True
    live_ready = False

    def size(self, signal) -> float:
        # Carry is not a directional bet — Kelly gives 0. Always use max_position_usdc.
        return self.max_position_usdc

    def scan(self, markets: list[dict]) -> list[Signal]:
        candidates = []
        for ev in markets:
            if not _is_binary(ev):
                continue
            if not _looks_eligible(ev):
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

        print(f"  [{self.name}] {len(signals)} carry signals ({len(candidates)} candidates)")
        return signals

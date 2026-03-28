from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Signal:
    """An opportunity identified by a strategy."""
    strategy: str
    market_id: str          # event slug
    market_title: str
    outcome: Literal["YES", "NO"]
    market_price: float     # price of the outcome token (0–1)
    p_hat: float            # estimated true probability (0–1)
    ev_pp: float            # EV in percentage points = (p_hat - market_price) * 100
    confidence: str         # "low" | "medium" | "high"
    closes: str             # ISO date e.g. "2026-04-29"
    url: str
    rationale: str = ""


@dataclass
class Trade:
    """A paper or live position."""
    id: str
    strategy: str
    market_id: str
    market_title: str
    outcome: str            # "YES" or "NO"
    amount_usdc: float      # dollars staked
    entry_price: float      # price at fill (0–1)
    shares: float           # amount_usdc / entry_price
    opened_at: str          # ISO datetime
    closes: str             # market close date
    url: str
    # filled on resolution:
    status: str = "open"    # "open" | "closed"
    exit_price: float = 0.0
    closed_at: str = ""
    pnl_usdc: float = 0.0
    resolved_outcome: str = ""
    notes: str = ""

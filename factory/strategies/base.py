"""Base Strategy class — all strategies implement this interface."""
from abc import ABC, abstractmethod
from ..models import Signal


class Strategy(ABC):
    name: str = "unnamed"
    mode: str = "paper"           # "paper" | "live"
    max_position_usdc: float = 10.0
    min_ev_pp: float = 10.0

    @abstractmethod
    def scan(self, markets: list[dict]) -> list[Signal]:
        """
        Examine the current market snapshot and return trading signals.
        markets: list of Gamma API event dicts (pre-fetched by runner).
        """
        ...

    def size(self, signal: Signal) -> float:
        """
        Return position size in USDC.
        Default: 25% Kelly criterion, capped at max_position_usdc.
        Subclasses can set min_position_usdc to override the floor.
        """
        p = signal.p_hat
        q = 1 - p
        mp = max(signal.market_price, 0.01)
        b = (1 - mp) / mp
        kelly = (b * p - q) / b if b > 0 else 0
        fraction = max(kelly * 0.25, 0)  # 25% Kelly, floored at 0
        size = min(fraction * self.max_position_usdc, self.max_position_usdc)
        min_size = getattr(self, "min_position_usdc", 1.0)
        return round(max(size, min_size) if size > 0 else 0, 2)

    def should_exit(self, trade: dict, current_price: float | None) -> bool:
        """
        Whether to close a position early (before market resolution).
        Default: hold to resolution.
        """
        return False

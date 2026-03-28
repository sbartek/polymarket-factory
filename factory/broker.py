"""Paper broker — simulates order fills, tracks trades in data/trades.csv."""
import csv
import uuid
from datetime import datetime
from pathlib import Path

from .models import Signal, Trade

TRADES_CSV = Path(__file__).parents[1] / "data" / "trades.csv"
TRADE_FIELDS = [
    "id", "strategy", "market_id", "market_title", "outcome",
    "amount_usdc", "entry_price", "shares", "opened_at", "closes", "url",
    "status", "exit_price", "closed_at", "pnl_usdc", "resolved_outcome", "notes",
]


class PaperBroker:
    """Simulates fills at market price + slippage. No real money involved."""

    def __init__(self, slippage: float = 0.005):
        self.slippage = slippage
        TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)

    # ── I/O ──────────────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if not TRADES_CSV.exists():
            return []
        with open(TRADES_CSV, newline="") as f:
            return list(csv.DictReader(f))

    def _save(self, trades: list[dict]):
        with open(TRADES_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(trades)

    # ── Public API ────────────────────────────────────────────────────────────

    def has_position(self, market_id: str, strategy: str) -> bool:
        return any(
            t["market_id"] == market_id and t["strategy"] == strategy and t["status"] == "open"
            for t in self._load()
        )

    def open_position(self, signal: Signal, amount_usdc: float) -> Trade:
        fill_price = min(signal.market_price + self.slippage, 0.99)
        trade = Trade(
            id=str(uuid.uuid4())[:8],
            strategy=signal.strategy,
            market_id=signal.market_id,
            market_title=signal.market_title,
            outcome=signal.outcome,
            amount_usdc=round(amount_usdc, 2),
            entry_price=round(fill_price, 4),
            shares=round(amount_usdc / fill_price, 4),
            opened_at=datetime.now().isoformat(timespec="seconds"),
            closes=signal.closes,
            url=signal.url,
        )
        trades = self._load()
        trades.append({f: getattr(trade, f, "") for f in TRADE_FIELDS})
        self._save(trades)
        return trade

    def close_position(self, trade_id: str, resolved_outcome: str):
        trades = self._load()
        for t in trades:
            if t["id"] == trade_id and t["status"] == "open":
                outcome = resolved_outcome.upper()
                shares = float(t["shares"])
                entry = float(t["entry_price"])
                amount = float(t["amount_usdc"])

                if outcome == t["outcome"]:
                    pnl = shares * 1.0 - amount   # shares pay $1 each at resolution
                else:
                    pnl = -amount                  # position worthless

                t["status"] = "closed"
                t["exit_price"] = 1.0 if outcome == t["outcome"] else 0.0
                t["closed_at"] = datetime.now().isoformat(timespec="seconds")
                t["pnl_usdc"] = round(pnl, 4)
                t["resolved_outcome"] = resolved_outcome
                self._save(trades)
                return

    def get_open_positions(self) -> list[dict]:
        return [t for t in self._load() if t["status"] == "open"]

    def get_all_trades(self) -> list[dict]:
        return self._load()

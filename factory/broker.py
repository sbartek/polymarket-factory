"""Paper broker — SQLite-backed trade state with optional legacy CSV import/export during migration."""
import csv
import uuid
from datetime import datetime
from pathlib import Path

from .db import FactoryDB, TRADE_FIELDS, TRADES_CSV
from .models import Signal, Trade
from .strategy_meta import ACTIVE_STRATEGIES, strategy_metadata


class PaperBroker:
    """Simulates fills at market price + slippage. No real money involved."""

    def __init__(self, slippage: float = 0.005, db: FactoryDB | None = None, run_id: str | None = None, export_csv: bool = True):
        self.slippage = slippage
        self.db = db or FactoryDB()
        self.run_id = run_id
        self.export_csv = export_csv
        TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
        self.db.ensure_trades_imported_from_csv(TRADES_CSV)
        if self.export_csv:
            self.export_trades_csv()

    def _load(self) -> list[dict]:
        return self.db.load_trades(mode="paper")

    def export_trades_csv(self):
        trades = self._load()
        with open(TRADES_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(trades)

    def has_position(self, market_id: str, strategy: str) -> bool:
        return self.db.has_open_position(market_id, strategy, mode="paper")

    def open_position(self, signal: Signal, amount_usdc: float) -> Trade:
        fill_price = min(signal.market_price + self.slippage, 0.99)
        meta = strategy_metadata().get(signal.strategy, {})
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
        self.db.insert_trade({
            **{f: getattr(trade, f, "") for f in TRADE_FIELDS},
            "run_id_opened": self.run_id,
            "lifecycle_group": "active" if signal.strategy in ACTIVE_STRATEGIES else "legacy",
            "time_window": meta.get("time_window"),
            "edge_type": meta.get("edge_type"),
        })
        if self.export_csv:
            self.export_trades_csv()
        return trade

    def close_position(self, trade_id: str, resolved_outcome: str):
        updated = self.db.close_trade(trade_id, resolved_outcome, run_id_closed=self.run_id)
        if updated and self.export_csv:
            self.export_trades_csv()

    def get_open_positions(self) -> list[dict]:
        return [t for t in self._load() if t["status"] == "open"]

    def get_all_trades(self) -> list[dict]:
        return self._load()

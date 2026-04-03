"""Live broker — routes orders to Polymarket CLOB. Same interface as PaperBroker."""
import uuid
from datetime import datetime

from . import clob as clob_api
from .db import FactoryDB, TRADE_FIELDS
from .models import Signal, Trade
from .strategy_meta import ACTIVE_STRATEGIES, strategy_metadata

LIVE_EXPOSURE_CAP_USDC = 100.0


class LiveBroker:
    """Places real orders on Polymarket CLOB. Hard cap: $100 total live exposure."""

    def __init__(self, db: FactoryDB | None = None, run_id: str | None = None):
        self.db = db or FactoryDB()
        self.run_id = run_id

    def _live_exposure(self) -> float:
        return sum(
            float(t.get("amount_usdc") or 0)
            for t in self.db.load_trades()
            if t.get("status") == "open" and t.get("mode") == "live"
        )

    def has_position(self, market_id: str, strategy: str) -> bool:
        return self.db.has_open_position(market_id, strategy, mode="live")

    def open_position(self, signal: Signal, amount_usdc: float, market: dict | None = None) -> Trade | None:
        if self._live_exposure() + amount_usdc > LIVE_EXPOSURE_CAP_USDC:
            print(f"  [live_broker] SKIP {signal.market_id}: would exceed ${LIVE_EXPOSURE_CAP_USDC} live exposure cap")
            return None

        if "carry:full-set" in (signal.rationale or ""):
            return self._open_full_set(signal, amount_usdc, market)
        return self._open_directional(signal, amount_usdc, market)

    def _open_full_set(self, signal: Signal, amount_usdc: float, market: dict | None) -> Trade | None:
        if not market:
            print(f"  [live_broker] SKIP {signal.market_id}: no market data for full-set")
            return None
        yes_id, no_id = clob_api.get_clob_token_ids(market)
        if not yes_id or not no_id:
            print(f"  [live_broker] SKIP {signal.market_id}: missing clobTokenIds")
            return None

        p_yes = signal.market_price
        p_no = 1.0 - p_yes
        # Buy equal number of full sets: N sets costs N*(p_yes + p_no) ≈ N
        n_sets = amount_usdc / max(p_yes + p_no, 0.01)
        yes_size = round(n_sets, 4)
        no_size = round(n_sets, 4)

        try:
            yes_resp = clob_api.place_market_order(yes_id, yes_size)
        except Exception as e:
            print(f"  [live_broker] ORDER FAILED (YES leg) {signal.market_id}: {e}")
            return None
        try:
            no_resp = clob_api.place_market_order(no_id, no_size)
        except Exception as e:
            print(f"  [live_broker] CRITICAL: YES leg filled but NO leg FAILED for {signal.market_id}: {e}")
            print(f"  [live_broker] CRITICAL: YES order ID {yes_resp.get('orderID','?')} — hedge manually!")
            return None

        clob_ids = f"{yes_resp.get('orderID', '?')},{no_resp.get('orderID', '?')}"
        fill_price = round(p_yes + p_no, 4)  # cost per full set
        notes = f"full-set,clob_ids={clob_ids}"
        return self._record_trade(signal, amount_usdc, fill_price, outcome="FULL_SET", notes=notes)

    def _open_directional(self, signal: Signal, amount_usdc: float, market: dict | None) -> Trade | None:
        if not market:
            print(f"  [live_broker] SKIP {signal.market_id}: no market data")
            return None
        yes_id, no_id = clob_api.get_clob_token_ids(market)
        token_id = yes_id if signal.outcome == "YES" else no_id
        if not token_id:
            print(f"  [live_broker] SKIP {signal.market_id}: missing token_id for {signal.outcome}")
            return None

        price = signal.market_price if signal.outcome == "YES" else (1.0 - signal.market_price)
        size = round(amount_usdc / max(price, 0.01), 4)

        try:
            resp = clob_api.place_market_order(token_id, size)
        except Exception as e:
            print(f"  [live_broker] ORDER FAILED {signal.market_id}: {e}")
            return None

        notes = f"clob_id={resp.get('orderID', '?')}"
        return self._record_trade(signal, amount_usdc, round(price, 4), notes=notes)

    def _record_trade(self, signal: Signal, amount_usdc: float, fill_price: float, outcome: str | None = None, notes: str = "") -> Trade:
        meta = strategy_metadata().get(signal.strategy, {})
        resolved_outcome = outcome or signal.outcome
        trade = Trade(
            id=str(uuid.uuid4())[:8],
            strategy=signal.strategy,
            market_id=signal.market_id,
            market_title=signal.market_title,
            outcome=resolved_outcome,
            amount_usdc=round(amount_usdc, 2),
            entry_price=fill_price,
            shares=round(amount_usdc / max(fill_price, 0.001), 4),
            opened_at=datetime.now().isoformat(timespec="seconds"),
            closes=signal.closes,
            url=signal.url,
            notes=notes,
        )
        self.db.insert_trade({
            **{f: getattr(trade, f, "") for f in TRADE_FIELDS},
            "run_id_opened": self.run_id,
            "lifecycle_group": "active" if signal.strategy in ACTIVE_STRATEGIES else "legacy",
            "time_window": meta.get("time_window"),
            "edge_type": meta.get("edge_type"),
            "mode": "live",
        })
        return trade

    def close_position(self, trade_id: str, resolved_outcome: str):
        self.db.close_trade(trade_id, resolved_outcome, run_id_closed=self.run_id)

    def get_open_positions(self) -> list[dict]:
        return [t for t in self.db.load_trades() if t.get("status") == "open" and t.get("mode") == "live"]

    def get_all_trades(self) -> list[dict]:
        return [t for t in self.db.load_trades() if t.get("mode") == "live"]

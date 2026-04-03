from factory.broker import PaperBroker
from factory.db import FactoryDB
from factory.live_broker import LiveBroker


def _insert_trade(db: FactoryDB, trade_id: str, *, mode: str) -> None:
    db.insert_trade({
        "id": trade_id,
        "strategy": "carry_rewards" if mode == "live" else "ev_news",
        "market_id": f"market-{trade_id}",
        "market_title": f"Market {trade_id}",
        "outcome": "YES",
        "amount_usdc": 10.0,
        "entry_price": 0.5,
        "shares": 20.0,
        "opened_at": "2026-04-03T10:00:00",
        "closes": "2026-05-01",
        "url": "",
        "status": "open",
        "mode": mode,
    })


def test_paper_broker_excludes_live_trades(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    _insert_trade(db, "paper1", mode="paper")
    _insert_trade(db, "live1", mode="live")
    broker = PaperBroker(db=db, export_csv=False)
    trades = broker.get_all_trades()
    assert len(trades) == 1
    assert trades[0]["mode"] == "paper"


def test_live_broker_excludes_paper_trades(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    _insert_trade(db, "paper1", mode="paper")
    _insert_trade(db, "live1", mode="live")
    broker = LiveBroker(db=db)
    trades = broker.get_all_trades()
    assert len(trades) == 1
    assert trades[0]["mode"] == "live"

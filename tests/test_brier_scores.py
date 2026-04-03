"""
Tests for Brier score tracking via FactoryDB.get_brier_score_data().

Key contract:
- Only closed paper trades with resolved_outcome IN ('YES', 'NO') are scored.
- Named-outcome markets (team names, etc.) are excluded.
- p_hat comes from the signal at the run that opened the trade.
- brier_score = (p_hat - actual)^2 where actual = exit_price (1.0 or 0.0).
"""
import uuid
from pathlib import Path

import pytest

from factory.db import FactoryDB


def _run(db: FactoryDB, mode: str = "paper") -> str:
    return db.start_run(mode=mode)


def _signal(db: FactoryDB, run_id: str, market_id: str, strategy: str,
            outcome: str, p_hat: float, market_price: float = 0.4):
    db.log_signal(run_id, strategy, {
        "strategy": strategy,
        "market_id": market_id,
        "market_title": f"Test market {market_id}",
        "outcome": outcome,
        "market_price": market_price,
        "p_hat": p_hat,
        "ev_pp": round((p_hat - market_price) * 100, 1),
        "confidence": "medium",
        "closes": "2026-06-01",
        "url": "",
        "rationale": "test",
    })


def _trade(db: FactoryDB, run_id: str, market_id: str, strategy: str,
           outcome: str, resolved_outcome: str, exit_price: float,
           p_hat_for_signal: float, mode: str = "paper"):
    trade_id = str(uuid.uuid4())[:8]
    _signal(db, run_id, market_id, strategy, outcome, p_hat_for_signal)
    db.insert_trade({
        "id": trade_id,
        "strategy": strategy,
        "market_id": market_id,
        "market_title": f"Test {market_id}",
        "outcome": outcome,
        "amount_usdc": 5.0,
        "entry_price": 0.4,
        "shares": 12.5,
        "opened_at": "2026-04-01T10:00:00",
        "closes": "2026-06-01",
        "url": "",
        "status": "open",
        "mode": mode,
        "run_id_opened": run_id,
    })
    db.close_trade(trade_id, resolved_outcome)
    return trade_id


def test_brier_score_correct_prediction(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = _run(db)
    _trade(db, run_id, "mkt-yes", "ev_news", outcome="YES",
           resolved_outcome="YES", exit_price=1.0, p_hat_for_signal=0.8)

    rows = db.get_brier_score_data()
    assert len(rows) == 1
    r = rows[0]
    assert r["strategy"] == "ev_news"
    assert r["actual"] == 1.0
    assert abs(r["p_hat"] - 0.8) < 1e-6
    assert abs(r["brier_score"] - (0.8 - 1.0) ** 2) < 1e-6


def test_brier_score_wrong_prediction(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = _run(db)
    _trade(db, run_id, "mkt-no", "ev_news", outcome="YES",
           resolved_outcome="NO", exit_price=0.0, p_hat_for_signal=0.7)

    rows = db.get_brier_score_data()
    assert len(rows) == 1
    assert abs(rows[0]["brier_score"] - 0.7 ** 2) < 1e-6
    assert rows[0]["actual"] == 0.0


def test_brier_score_excludes_named_outcome_markets(tmp_path):
    """Sports markets with team-name resolved_outcome must be excluded."""
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = _run(db)
    _trade(db, run_id, "mkt-sports", "stale_market", outcome="YES",
           resolved_outcome="JESSICA PEGULA", exit_price=0.0, p_hat_for_signal=0.75)

    rows = db.get_brier_score_data()
    assert rows == []


def test_brier_score_excludes_live_trades(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = _run(db, mode="live")
    _trade(db, run_id, "mkt-live", "carry_rewards", outcome="YES",
           resolved_outcome="YES", exit_price=1.0, p_hat_for_signal=0.9,
           mode="live")

    rows = db.get_brier_score_data()
    assert rows == []


def test_brier_score_excludes_open_trades(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = _run(db)
    _signal(db, run_id, "mkt-open", "ev_news", "YES", 0.65)
    db.insert_trade({
        "id": "open1",
        "strategy": "ev_news",
        "market_id": "mkt-open",
        "market_title": "Open market",
        "outcome": "YES",
        "amount_usdc": 5.0,
        "entry_price": 0.4,
        "shares": 12.5,
        "opened_at": "2026-04-01T10:00:00",
        "closes": "2026-06-01",
        "url": "",
        "status": "open",
        "mode": "paper",
        "run_id_opened": run_id,
    })

    rows = db.get_brier_score_data()
    assert rows == []


def test_brier_score_filters_by_strategy(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = _run(db)
    _trade(db, run_id, "mkt-ev", "ev_news", "YES", "YES", 1.0, 0.8)
    _trade(db, run_id, "mkt-stale", "stale_market", "NO", "NO", 1.0, 0.9)

    rows_ev = db.get_brier_score_data(strategies=["ev_news"])
    assert len(rows_ev) == 1
    assert rows_ev[0]["strategy"] == "ev_news"

    rows_all = db.get_brier_score_data()
    assert len(rows_all) == 2


def test_brier_score_multiple_trades(tmp_path):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = _run(db)
    _trade(db, run_id, "mkt-a", "ev_news", "YES", "YES", 1.0, 0.9)   # BS = 0.01
    _trade(db, run_id, "mkt-b", "ev_news", "YES", "NO",  0.0, 0.6)   # BS = 0.36

    rows = db.get_brier_score_data(strategies=["ev_news"])
    assert len(rows) == 2
    mean_bs = sum(r["brier_score"] for r in rows) / len(rows)
    assert abs(mean_bs - (0.01 + 0.36) / 2) < 1e-6

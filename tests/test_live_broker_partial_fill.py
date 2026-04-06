"""
Tests for live_broker partial-fill handling:
- _place_with_retry() retries once on failure, returns None after two failures
- _open_full_set() records PARTIAL_YES_UNHEDGED trade when NO leg fails
- _open_full_set() returns None (no record) when YES leg fails
"""
import factory.clob as clob_module
from factory.db import FactoryDB
from factory.live_broker import LiveBroker
from factory.models import Signal


def _signal(market_id: str = "test-market") -> Signal:
    return Signal(
        strategy="carry_rewards",
        market_id=market_id,
        market_title="Test market",
        outcome="YES",
        market_price=0.50,
        p_hat=0.54,
        ev_pp=4.0,
        confidence="medium",
        closes="2026-12-31",
        url="",
        rationale="carry:full-set",
    )


def _market_dict(yes_id: str = "yes-token", no_id: str = "no-token") -> dict:
    import json
    return {"clobTokenIds": json.dumps([yes_id, no_id])}


# --- _place_with_retry ---

def test_place_with_retry_returns_response_on_first_success(tmp_path, monkeypatch):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = LiveBroker(db=db, run_id="run1")

    monkeypatch.setattr(clob_module, "place_market_order", lambda token_id, size: {"orderID": "order-1"})
    result = broker._place_with_retry("tok", 1.0, leg="NO", context="mkt")
    assert result == {"orderID": "order-1"}


def test_place_with_retry_retries_once_and_succeeds(tmp_path, monkeypatch):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = LiveBroker(db=db, run_id="run1")

    calls = {"n": 0}
    def flaky(token_id, size):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("timeout")
        return {"orderID": "order-2"}

    monkeypatch.setattr(clob_module, "place_market_order", flaky)
    monkeypatch.setattr("time.sleep", lambda _: None)
    result = broker._place_with_retry("tok", 1.0, leg="NO", context="mkt")
    assert result == {"orderID": "order-2"}
    assert calls["n"] == 2


def test_place_with_retry_returns_none_after_two_failures(tmp_path, monkeypatch):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    broker = LiveBroker(db=db, run_id="run1")

    monkeypatch.setattr(clob_module, "place_market_order", lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
    monkeypatch.setattr("time.sleep", lambda _: None)
    result = broker._place_with_retry("tok", 1.0, leg="NO", context="mkt")
    assert result is None


# --- _open_full_set partial fill ---

def test_open_full_set_records_partial_when_no_leg_fails(tmp_path, monkeypatch):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = db.start_run(mode="live")
    broker = LiveBroker(db=db, run_id=run_id)

    call_count = {"n": 0}
    def side_effect(token_id, size):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"orderID": "yes-order-123"}
        raise RuntimeError("NO leg timeout")

    monkeypatch.setattr(clob_module, "place_market_order", side_effect)
    monkeypatch.setattr("time.sleep", lambda _: None)

    trade = broker._open_full_set(_signal(), 10.0, _market_dict())

    # Trade is recorded despite NO failing
    assert trade is not None
    assert trade.outcome == "PARTIAL_YES_UNHEDGED"
    assert "yes-order-123" in trade.notes
    assert "no_failed" in trade.notes

    # Visible in open positions
    open_positions = broker.get_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0]["outcome"] == "PARTIAL_YES_UNHEDGED"


def test_open_full_set_logs_error_event_when_no_leg_fails(tmp_path, monkeypatch):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = db.start_run(mode="live")
    broker = LiveBroker(db=db, run_id=run_id)

    logged = []
    original_log_event = db.log_event
    monkeypatch.setattr(db, "log_event", lambda *args, **kwargs: (logged.append((args, kwargs)), original_log_event(*args, **kwargs)))

    call_count = {"n": 0}
    def side_effect(token_id, size):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"orderID": "yes-456"}
        raise RuntimeError("fail")

    monkeypatch.setattr(clob_module, "place_market_order", side_effect)
    monkeypatch.setattr("time.sleep", lambda _: None)

    broker._open_full_set(_signal(), 10.0, _market_dict())

    error_calls = [e for e in logged if "error" in e[0]]
    assert len(error_calls) >= 1
    assert any("partial_fill_unhedged_yes" in str(e) for e in logged)


def test_open_full_set_returns_none_when_yes_leg_fails(tmp_path, monkeypatch):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = db.start_run(mode="live")
    broker = LiveBroker(db=db, run_id=run_id)

    monkeypatch.setattr(clob_module, "place_market_order", lambda *_: (_ for _ in ()).throw(RuntimeError("YES fail")))

    trade = broker._open_full_set(_signal(), 10.0, _market_dict())

    assert trade is None
    assert broker.get_open_positions() == []


def test_open_full_set_records_full_set_when_both_legs_succeed(tmp_path, monkeypatch):
    db = FactoryDB(path=tmp_path / "test.sqlite3")
    run_id = db.start_run(mode="live")
    broker = LiveBroker(db=db, run_id=run_id)

    call_count = {"n": 0}
    def succeed(token_id, size):
        call_count["n"] += 1
        return {"orderID": f"order-{call_count['n']}"}

    monkeypatch.setattr(clob_module, "place_market_order", succeed)

    trade = broker._open_full_set(_signal(), 10.0, _market_dict())

    assert trade is not None
    assert trade.outcome == "FULL_SET"
    assert "full-set" in trade.notes

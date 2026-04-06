"""Integration tests for dedup + execute flow.

Verifies that the runner's dedup checks (broker.has_position, db.has_recent_signal,
24h cooldown) actually prevent double-trades across runs.
Uses real FactoryDB (with tmp_path) and PaperBroker — no mocking.
"""
from datetime import UTC, datetime, timedelta

import pytest

from factory.db import FactoryDB
from factory.broker import PaperBroker
from factory.models import Signal


def _make_signal(
    strategy: str = "ev_news",
    market_id: str = "market-abc",
    outcome: str = "YES",
    market_price: float = 0.40,
    p_hat: float = 0.55,
) -> Signal:
    return Signal(
        strategy=strategy,
        market_id=market_id,
        market_title="Will X happen?",
        outcome=outcome,
        market_price=market_price,
        p_hat=p_hat,
        ev_pp=(p_hat - market_price) * 100,
        confidence="medium",
        closes="2026-05-01",
        url="https://polymarket.com/event/test",
        rationale="test signal",
    )


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


@pytest.fixture
def broker(db):
    run_id = db.start_run(mode="paper", notes="test run")
    return PaperBroker(db=db, run_id=run_id)


# ---------- a) duplicate position skipped ----------

def test_duplicate_position_skipped(broker):
    """Opening a position makes has_position return True for the same (market, strategy)."""
    signal = _make_signal(strategy="ev_news", market_id="market-abc")

    assert broker.has_position("market-abc", "ev_news") is False

    broker.open_position(signal, amount_usdc=10.0)

    assert broker.has_position("market-abc", "ev_news") is True


# ---------- b) recent signal cooldown ----------

def test_recent_signal_cooldown(db):
    """A signal logged now triggers the 24h cooldown for its (strategy, market) pair only."""
    run_id = db.start_run(mode="paper", notes="cooldown test")

    db.log_signal(
        run_id=run_id,
        strategy="ev_news",
        signal={
            "market_id": "market-abc",
            "market_title": "Will X happen?",
            "outcome": "YES",
            "market_price": 0.40,
            "p_hat": 0.55,
            "ev_pp": 15.0,
            "confidence": "medium",
            "closes": "2026-05-01",
            "url": "https://polymarket.com/event/test",
            "rationale": "test",
        },
    )

    # Same strategy + market => blocked
    assert db.has_recent_signal("ev_news", "market-abc", hours=24.0) is True

    # Same strategy, different market => not blocked
    assert db.has_recent_signal("ev_news", "market-xyz", hours=24.0) is False

    # Different strategy, same market => not blocked
    assert db.has_recent_signal("spread_arb_v2", "market-abc", hours=24.0) is False


# ---------- c) cooldown expires ----------

def test_cooldown_expires(db):
    """A signal older than 24h no longer triggers the cooldown."""
    run_id = db.start_run(mode="paper", notes="expire test")

    # Insert a signal with a backdated created_at (25 hours ago)
    old_ts = (datetime.now(UTC) - timedelta(hours=25)).isoformat(timespec="seconds")

    with db._connect() as conn:
        conn.execute(
            """INSERT INTO signals
               (run_id, strategy, market_id, market_title, outcome,
                market_price, p_hat, ev_pp, confidence, closes, url,
                rationale, phase, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, "ev_news", "market-abc", "Will X happen?", "YES",
                0.40, 0.55, 15.0, "medium", "2026-05-01",
                "https://polymarket.com/event/test", "test", "combined", old_ts,
            ),
        )
        conn.commit()

    assert db.has_recent_signal("ev_news", "market-abc", hours=24.0) is False

    # Sanity: with a longer window it should still be found
    assert db.has_recent_signal("ev_news", "market-abc", hours=26.0) is True


# ---------- d) different strategy not blocked ----------

def test_different_strategy_not_blocked(broker):
    """A position for strategy A does not block strategy B on the same market."""
    signal_a = _make_signal(strategy="ev_news", market_id="market-abc")

    broker.open_position(signal_a, amount_usdc=10.0)

    # Strategy A is blocked
    assert broker.has_position("market-abc", "ev_news") is True

    # Strategy B is not blocked
    assert broker.has_position("market-abc", "spread_arb_v2") is False

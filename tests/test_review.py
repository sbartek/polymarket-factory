"""Tests for the 24h review briefing module."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from factory.db import FactoryDB
from factory.review import (
    exposure_vs_caps,
    expiring_soon,
    format_review,
    portfolio_24h,
    strategy_health_7d,
    watch_list,
)


@pytest.fixture
def db(tmp_path):
    """SQLite-backed FactoryDB for testing."""
    return FactoryDB(path=tmp_path / "test.db")


def _insert_trade(db, strategy="stale_market", amount=10.0, status="open", pnl=0.0,
                  opened_at=None, closed_at=None, closes="", mode="paper",
                  outcome="YES", resolved_outcome="", market_title="Test market"):
    now = datetime.now(UTC).isoformat(timespec="seconds")
    opened_at = opened_at or now
    import uuid
    trade = {
        "id": uuid.uuid4().hex[:12],
        "strategy": strategy,
        "market_id": f"market-{uuid.uuid4().hex[:6]}",
        "market_title": market_title,
        "outcome": outcome,
        "amount_usdc": amount,
        "entry_price": 0.5,
        "shares": amount / 0.5,
        "opened_at": opened_at,
        "closes": closes,
        "url": "",
        "status": status,
        "exit_price": 0.0,
        "closed_at": closed_at or "",
        "pnl_usdc": pnl,
        "resolved_outcome": resolved_outcome,
        "notes": "",
        "mode": mode,
    }
    db.insert_trade(trade)
    return trade


def _insert_decision(db, run_id, strategy, decision="skip", reason="cap_check", market_id="m1"):
    with db._conn() as (conn, cur):
        cur.execute(
            "INSERT INTO decisions (run_id, strategy, market_id, decision_type, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (run_id, strategy, market_id, "execution", decision, reason, datetime.now(UTC).isoformat(timespec="seconds")),
        )


def _insert_signal(db, run_id, strategy, ev_pp=10.0, market_id="m1", market_title="Signal market", outcome="YES"):
    with db._conn() as (conn, cur):
        cur.execute(
            "INSERT INTO signals (run_id, strategy, market_id, market_title, outcome, market_price, p_hat, ev_pp, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (run_id, strategy, market_id, market_title, outcome, 0.5, 0.6, ev_pp, datetime.now(UTC).isoformat(timespec="seconds")),
        )


class TestPortfolio24h:
    def test_empty_db(self, db):
        result = portfolio_24h(db)
        assert result["opened_count"] == 0
        assert result["closed_count"] == 0
        assert result["open_count"] == 0

    def test_counts_recent_trades(self, db):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        old = (datetime.now(UTC) - timedelta(hours=48)).isoformat(timespec="seconds")
        _insert_trade(db, opened_at=now, status="open")
        _insert_trade(db, opened_at=now, status="closed", closed_at=now, pnl=5.0, resolved_outcome="YES")
        _insert_trade(db, opened_at=old, status="closed", closed_at=old, pnl=-3.0, resolved_outcome="NO")
        result = portfolio_24h(db)
        assert result["opened_count"] == 2  # both recent
        assert result["closed_count"] == 1  # only recent closed
        assert result["closed_pnl"] == 5.0
        assert result["open_count"] == 1


class TestExpiringSoon:
    def test_finds_expiring(self, db):
        soon = (datetime.now(UTC) + timedelta(hours=12)).isoformat(timespec="seconds")
        far = (datetime.now(UTC) + timedelta(hours=72)).isoformat(timespec="seconds")
        _insert_trade(db, closes=soon, status="open")
        _insert_trade(db, closes=far, status="open")
        result = expiring_soon(db)
        assert len(result) == 1
        assert result[0]["closes"] == soon

    def test_ignores_closed_positions(self, db):
        soon = (datetime.now(UTC) + timedelta(hours=12)).isoformat(timespec="seconds")
        _insert_trade(db, closes=soon, status="closed", closed_at=datetime.now(UTC).isoformat(timespec="seconds"), pnl=1.0, resolved_outcome="YES")
        result = expiring_soon(db)
        assert len(result) == 0


class TestStrategyHealth7d:
    def test_aggregates_correctly(self, db):
        now = datetime.now(UTC).isoformat(timespec="seconds")
        for _ in range(3):
            _insert_trade(db, strategy="stale_market", status="closed", closed_at=now, pnl=2.0, resolved_outcome="YES")
        _insert_trade(db, strategy="stale_market", status="closed", closed_at=now, pnl=-5.0, resolved_outcome="NO")
        result = strategy_health_7d(db)
        assert len(result) == 1
        assert int(result[0]["wins"]) == 3
        assert int(result[0]["total"]) == 4
        assert float(result[0]["pnl"]) == 1.0

    def test_excludes_old_trades(self, db):
        old = (datetime.now(UTC) - timedelta(days=10)).isoformat(timespec="seconds")
        _insert_trade(db, status="closed", closed_at=old, pnl=5.0, resolved_outcome="YES")
        result = strategy_health_7d(db)
        assert len(result) == 0


class TestExposureVsCaps:
    def test_sums_by_mode(self, db):
        _insert_trade(db, amount=30.0, mode="paper")
        _insert_trade(db, amount=20.0, mode="paper")
        _insert_trade(db, amount=10.0, mode="live")
        result = exposure_vs_caps(db)
        assert result["paper_total"] == 50.0
        assert result["live_total"] == 10.0

    def test_near_cap_detection(self, db):
        # stale_market cap is 50.0 — put 40 in (80%, above 70% threshold)
        _insert_trade(db, strategy="stale_market", amount=40.0, mode="paper")
        result = exposure_vs_caps(db)
        assert len(result["near_cap"]) == 1
        assert result["near_cap"][0]["strategy"] == "stale_market"


class TestWatchList:
    def test_finds_blocked_signals(self, db):
        run_id = db.start_run(mode="paper")
        _insert_signal(db, run_id, "ev_news", ev_pp=15.0, market_id="m1", market_title="Blocked signal")
        _insert_decision(db, run_id, "ev_news", decision="skip", reason="cap_check: exceeded", market_id="m1")
        result = watch_list(db)
        assert len(result) == 1
        assert result[0]["strategy"] == "ev_news"

    def test_ignores_low_ev(self, db):
        run_id = db.start_run(mode="paper")
        _insert_signal(db, run_id, "ev_news", ev_pp=3.0, market_id="m1")
        _insert_decision(db, run_id, "ev_news", decision="skip", reason="cap_check", market_id="m1")
        result = watch_list(db)
        assert len(result) == 0


class TestFormatReview:
    def test_contains_all_sections(self):
        portfolio = {
            "opened_count": 3, "opened_staked": 15.0,
            "closed_count": 2, "closed_pnl": 4.50,
            "open_count": 10, "open_exposure": 80.0,
            "unrealized_now": 5.0, "unrealized_24h": 2.0, "unrealized_delta": 3.0,
        }
        expiring = [{"strategy": "ev_news", "market_title": "Test expiring market", "closes": "2026-04-16", "amount_usdc": 10.0}]
        health = [{"strategy": "stale_market", "total": 5, "wins": 4, "pnl": 6.20}]
        loss_streaks = {"thin_market_impact_fade": {"streak": 8, "total_lost": 12.50, "last_outcome": "YES"}}
        exposure = {"paper_total": 80.0, "live_total": 15.0, "near_cap": [{"strategy": "ev_news", "exposure": 38.0, "cap": 40.0, "mode": "paper"}]}
        watches = [{"strategy": "stale_market", "outcome": "YES", "market_title": "Watched market", "ev_pp": 12.0, "reason": "cap_check: exceeded"}]

        msg = format_review(portfolio, expiring, health, loss_streaks, exposure, watches)

        assert "*24h Review" in msg
        assert "Portfolio 24h" in msg
        assert "Opened: 3" in msg
        assert "$+4.50" in msg
        assert "Expiring 48h" in msg
        assert "ev_news" in msg
        assert "Strategy 7d" in msg
        assert "stale_market" in msg
        assert "!! thin_market_impact_fade" in msg
        assert "Exposure:" in msg
        assert "Paper $80.00" in msg
        assert "Near cap:" in msg
        assert "Watch list:" in msg

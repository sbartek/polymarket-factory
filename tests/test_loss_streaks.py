"""Tests for the consecutive loss streak detection."""
import tempfile
from pathlib import Path

from factory.db import FactoryDB


def _make_db():
    db = FactoryDB(path=Path(tempfile.mktemp(suffix=".db")))
    return db


def _insert_trade(db, strategy, outcome, resolved_outcome, pnl, closed_at):
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO trades (id, strategy, market_id, market_title, outcome, amount_usdc,
               shares, entry_price, opened_at, closes, url, status, exit_price, closed_at, pnl_usdc,
               resolved_outcome, notes, mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?, ?, ?, '', 'paper')""",
            (
                f"{strategy}-{closed_at}", strategy, f"m-{closed_at}", "Test market",
                outcome, 5.0, 5.0, 0.5, "2026-04-01T00:00:00", "2026-04-10", "",
                1.0 if resolved_outcome == outcome else 0.0,
                closed_at, pnl, resolved_outcome,
            ),
        )
        conn.commit()


class TestLossStreaks:
    def test_no_streaks_when_no_trades(self):
        db = _make_db()
        assert db.get_loss_streaks(min_streak=3) == {}

    def test_detects_5_consecutive_losses(self):
        db = _make_db()
        # 5 losses (betting NO, market resolves YES)
        for i in range(5):
            _insert_trade(db, "stale_market", "NO", "YES", -5.0, f"2026-04-0{i+1}T10:00:00")
        result = db.get_loss_streaks(min_streak=5)
        assert "stale_market" in result
        assert result["stale_market"]["streak"] == 5
        assert result["stale_market"]["total_lost"] == 25.0
        assert result["stale_market"]["last_outcome"] == "NO"

    def test_win_breaks_streak(self):
        db = _make_db()
        # 3 losses, then 1 win, then 3 losses (most recent first = 3 losses)
        _insert_trade(db, "ev_news", "YES", "YES", 5.0, "2026-04-04T10:00:00")  # win (breaks streak)
        for i in range(3):
            _insert_trade(db, "ev_news", "YES", "NO", -5.0, f"2026-04-0{i+5}T10:00:00")  # losses after win
        result = db.get_loss_streaks(min_streak=3)
        assert "ev_news" in result
        assert result["ev_news"]["streak"] == 3

    def test_streak_below_threshold_excluded(self):
        db = _make_db()
        for i in range(4):
            _insert_trade(db, "ev_news", "NO", "YES", -5.0, f"2026-04-0{i+1}T10:00:00")
        result = db.get_loss_streaks(min_streak=5)
        assert "ev_news" not in result

    def test_multiple_strategies(self):
        db = _make_db()
        # stale_market: 5 losses
        for i in range(5):
            _insert_trade(db, "stale_market", "NO", "YES", -5.0, f"2026-04-0{i+1}T10:00:00")
        # ev_news: 3 losses (below threshold of 5)
        for i in range(3):
            _insert_trade(db, "ev_news", "YES", "NO", -5.0, f"2026-04-0{i+1}T10:00:00")
        result = db.get_loss_streaks(min_streak=5)
        assert "stale_market" in result
        assert "ev_news" not in result

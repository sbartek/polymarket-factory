"""Tests for ev_news strategy-level dedup.

Verifies that _analyze_topic skips markets that already have a recent signal
in the DB, saving LLM calls.
"""
import sqlite3
from unittest.mock import patch

import pytest

from factory.strategies.ev_news import EvNewsStrategy


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "test.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY,
            strategy TEXT NOT NULL,
            market_id TEXT NOT NULL,
            consumed_by_run_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


@pytest.fixture
def strategy():
    return EvNewsStrategy()


def _fake_market(slug: str, title: str) -> dict:
    return {
        "slug": slug,
        "title": title,
        "volume24hr": 50000,
        "endDate": "2026-04-15",
        "outcomePrices": '[0.45, 0.55]',
    }


class _DedupDB:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def has_recent_signal(self, strategy: str, market_id: str, hours: float = 24.0) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM signals
            WHERE strategy = ?
              AND market_id = ?
              AND consumed_by_run_id IS NOT NULL
              AND created_at >= datetime('now', ?)
            LIMIT 1
            """,
            (strategy, market_id, f"-{hours} hours"),
        ).fetchone()
        return row is not None


def _seed_signal(db: sqlite3.Connection, market_id: str):
    """Insert a recent consumed signal so has_recent_signal returns True."""
    db.execute(
        """
        INSERT INTO signals (strategy, market_id, consumed_by_run_id, created_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        ("ev_news", market_id, "exec-run"),
    )
    db.commit()


class TestAnalyzeTopicDedup:
    """Test that _analyze_topic filters out markets with recent signals."""

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch.object(EvNewsStrategy, "_fetch_news", return_value=[])
    @patch("factory.strategies.ev_news.call_claude")
    def test_skips_market_with_recent_signal(self, mock_claude, _mock_news, mock_fetch, strategy, db):
        """Market with a recent signal should be filtered out before calling Claude."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
        ]

        # Seed a signal for this market
        _seed_signal(db, "strait-of-hormuz")

        # _analyze_topic should skip the market and return empty (no Claude call)
        signals = strategy._analyze_topic("iran", [], db=_DedupDB(db))

        assert signals == []
        mock_claude.assert_not_called()

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch.object(EvNewsStrategy, "_fetch_news", return_value=[])
    @patch("factory.strategies.ev_news.call_claude")
    def test_keeps_market_without_recent_signal(self, mock_claude, _mock_news, mock_fetch, strategy, db):
        """Market without a recent signal should be sent to Claude."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
        ]
        # Return no signals from Claude
        mock_claude.return_value = "<signals>[]</signals>"

        signals = strategy._analyze_topic("iran", [], db=_DedupDB(db))

        assert signals == []
        mock_claude.assert_called_once()

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch.object(EvNewsStrategy, "_fetch_news", return_value=[])
    @patch("factory.strategies.ev_news.call_claude")
    def test_partial_dedup_some_markets_kept(self, mock_claude, _mock_news, mock_fetch, strategy, db):
        """Only markets with recent signals are filtered; others proceed."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
            _fake_market("iran-sanctions", "New Iran sanctions?"),
        ]
        mock_claude.return_value = "<signals>[]</signals>"

        # Only seed signal for one market
        _seed_signal(db, "strait-of-hormuz")

        signals = strategy._analyze_topic("iran", [], db=_DedupDB(db))

        # Claude should be called (iran-sanctions is still eligible)
        mock_claude.assert_called_once()
        # The prompt should contain iran-sanctions but not strait-of-hormuz
        prompt = mock_claude.call_args[0][0]
        assert "iran-sanctions" in prompt or "Iran sanctions" in prompt

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch.object(EvNewsStrategy, "_fetch_news", return_value=[])
    @patch("factory.strategies.ev_news.call_claude")
    def test_no_db_skips_dedup(self, mock_claude, _mock_news, mock_fetch, strategy):
        """When db is None, no dedup happens (graceful degradation)."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
        ]
        mock_claude.return_value = "<signals>[]</signals>"

        signals = strategy._analyze_topic("iran", [], db=None)

        # Claude should still be called
        mock_claude.assert_called_once()

"""Tests for ev_news strategy-level dedup.

Verifies that _analyze_topic skips markets that already have a recent signal
in the DB, saving LLM calls.
"""
from unittest.mock import patch, MagicMock

import pytest

from factory.db import FactoryDB
from factory.strategies.ev_news import EvNewsStrategy


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


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


def _seed_signal(db: FactoryDB, market_id: str):
    """Insert a recent consumed signal into the DB so has_recent_signal returns True."""
    run_id = db.start_run(mode="paper", notes="seed")
    db.log_signal(
        run_id=run_id,
        strategy="ev_news",
        signal={
            "market_id": market_id,
            "market_title": "Test",
            "outcome": "YES",
            "market_price": 0.40,
            "p_hat": 0.55,
            "ev_pp": 15.0,
            "confidence": "medium",
            "closes": "2026-04-15",
            "url": "https://polymarket.com/event/test",
            "rationale": "test",
        },
        phase="scan",
    )
    # Mark as consumed so has_recent_signal (which only checks consumed signals) finds it
    rows = db.get_unconsumed_signals()
    if rows:
        exec_run = db.start_run(mode="paper", notes="exec")
        db.mark_signals_consumed([rows[0]["id"]], exec_run)


class TestAnalyzeTopicDedup:
    """Test that _analyze_topic filters out markets with recent signals."""

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch("factory.strategies.ev_news.call_claude")
    def test_skips_market_with_recent_signal(self, mock_claude, mock_fetch, strategy, db):
        """Market with a recent signal should be filtered out before calling Claude."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
        ]

        # Seed a signal for this market
        _seed_signal(db, "strait-of-hormuz")

        # _analyze_topic should skip the market and return empty (no Claude call)
        signals = strategy._analyze_topic("iran", [], db=db)

        assert signals == []
        mock_claude.assert_not_called()

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch("factory.strategies.ev_news.call_claude")
    def test_keeps_market_without_recent_signal(self, mock_claude, mock_fetch, strategy, db):
        """Market without a recent signal should be sent to Claude."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
        ]
        # Return no signals from Claude
        mock_claude.return_value = "<signals>[]</signals>"

        signals = strategy._analyze_topic("iran", [], db=db)

        assert signals == []
        mock_claude.assert_called_once()

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch("factory.strategies.ev_news.call_claude")
    def test_partial_dedup_some_markets_kept(self, mock_claude, mock_fetch, strategy, db):
        """Only markets with recent signals are filtered; others proceed."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
            _fake_market("iran-sanctions", "New Iran sanctions?"),
        ]
        mock_claude.return_value = "<signals>[]</signals>"

        # Only seed signal for one market
        _seed_signal(db, "strait-of-hormuz")

        signals = strategy._analyze_topic("iran", [], db=db)

        # Claude should be called (iran-sanctions is still eligible)
        mock_claude.assert_called_once()
        # The prompt should contain iran-sanctions but not strait-of-hormuz
        prompt = mock_claude.call_args[0][0]
        assert "iran-sanctions" in prompt or "Iran sanctions" in prompt

    @patch("factory.strategies.ev_news.fetch_by_tag")
    @patch("factory.strategies.ev_news.call_claude")
    def test_no_db_skips_dedup(self, mock_claude, mock_fetch, strategy):
        """When db is None, no dedup happens (graceful degradation)."""
        mock_fetch.return_value = [
            _fake_market("strait-of-hormuz", "Will Iran close Strait of Hormuz?"),
        ]
        mock_claude.return_value = "<signals>[]</signals>"

        signals = strategy._analyze_topic("iran", [], db=None)

        # Claude should still be called
        mock_claude.assert_called_once()

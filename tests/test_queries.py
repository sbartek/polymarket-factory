"""Unit tests for factory/queries.py helper functions."""
from __future__ import annotations

import pytest

from factory.db import FactoryDB
from factory.queries import (
    get_correlated_pairs_checks,
    get_decisions,
    get_decisions_summary,
    get_latest_runs,
    get_resolution_hunter_checks,
    get_spread_arb_baskets,
    get_stale_market_checks,
)


@pytest.fixture
def db(tmp_path):
    return FactoryDB(path=tmp_path / "test.sqlite3")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_run(db: FactoryDB, mode: str = "dry_run") -> str:
    run_id = db.start_run(mode)
    db.finish_run(run_id, "success", markets_fetched=10)
    return run_id


def _insert_decision(db: FactoryDB, run_id: str, strategy: str = "ev_news", decision_type: str = "execution", decision: str = "open"):
    db.log_decision(run_id, decision_type=decision_type, decision=decision, strategy=strategy, market_id="m1", reason="test")


# ---------------------------------------------------------------------------
# get_latest_runs
# ---------------------------------------------------------------------------

class TestGetLatestRuns:
    def test_returns_empty_for_no_runs(self, db):
        assert get_latest_runs(db) == []

    def test_returns_single_run(self, db):
        run_id = _insert_run(db)
        runs = get_latest_runs(db)
        assert len(runs) == 1
        assert runs[0]["id"] == run_id
        assert runs[0]["status"] == "success"
        assert runs[0]["markets_fetched"] == 10

    def test_returns_n_runs_newest_first(self, db):
        ids = [_insert_run(db) for _ in range(4)]
        runs = get_latest_runs(db, n=3)
        assert len(runs) == 3
        # all returned ids should be from the inserted set
        assert all(r["id"] in ids for r in runs)

    def test_n_larger_than_available(self, db):
        _insert_run(db)
        runs = get_latest_runs(db, n=100)
        assert len(runs) == 1


# ---------------------------------------------------------------------------
# get_decisions
# ---------------------------------------------------------------------------

class TestGetDecisions:
    def test_returns_empty_when_no_decisions(self, db):
        assert get_decisions(db) == []

    def test_returns_all_decisions_unfiltered(self, db):
        run_id = _insert_run(db)
        _insert_decision(db, run_id, strategy="ev_news")
        _insert_decision(db, run_id, strategy="spread_arb")
        rows = get_decisions(db)
        assert len(rows) == 2

    def test_filter_by_run_id(self, db):
        r1 = _insert_run(db)
        r2 = _insert_run(db)
        _insert_decision(db, r1)
        _insert_decision(db, r2)
        rows = get_decisions(db, run_id=r1)
        assert len(rows) == 1
        assert rows[0]["run_id"] == r1

    def test_filter_by_strategy(self, db):
        run_id = _insert_run(db)
        _insert_decision(db, run_id, strategy="ev_news")
        _insert_decision(db, run_id, strategy="spread_arb")
        rows = get_decisions(db, strategy="spread_arb")
        assert len(rows) == 1
        assert rows[0]["strategy"] == "spread_arb"

    def test_filter_by_run_id_and_strategy(self, db):
        r1 = _insert_run(db)
        r2 = _insert_run(db)
        _insert_decision(db, r1, strategy="ev_news")
        _insert_decision(db, r2, strategy="ev_news")
        rows = get_decisions(db, run_id=r1, strategy="ev_news")
        assert len(rows) == 1
        assert rows[0]["run_id"] == r1

    def test_limit_respected(self, db):
        run_id = _insert_run(db)
        for _ in range(10):
            _insert_decision(db, run_id)
        rows = get_decisions(db, limit=3)
        assert len(rows) == 3

    def test_no_run_id_match_returns_empty(self, db):
        run_id = _insert_run(db)
        _insert_decision(db, run_id)
        assert get_decisions(db, run_id="nonexistent") == []


# ---------------------------------------------------------------------------
# get_decisions_summary
# ---------------------------------------------------------------------------

class TestGetDecisionsSummary:
    def test_empty(self, db):
        assert get_decisions_summary(db) == []

    def test_counts_grouped_by_type_and_decision(self, db):
        run_id = _insert_run(db)
        _insert_decision(db, run_id, decision_type="execution", decision="open")
        _insert_decision(db, run_id, decision_type="execution", decision="open")
        _insert_decision(db, run_id, decision_type="size_check", decision="skip")
        rows = get_decisions_summary(db)
        counts = {(r["decision_type"], r["decision"]): r["cnt"] for r in rows}
        assert counts[("execution", "open")] == 2
        assert counts[("size_check", "skip")] == 1

    def test_filter_by_run_id(self, db):
        r1 = _insert_run(db)
        r2 = _insert_run(db)
        _insert_decision(db, r1, decision_type="execution", decision="open")
        _insert_decision(db, r2, decision_type="execution", decision="skip")
        rows = get_decisions_summary(db, run_id=r1)
        assert len(rows) == 1
        assert rows[0]["decision"] == "open"


# ---------------------------------------------------------------------------
# Strategy detail table queries
# ---------------------------------------------------------------------------

class TestStrategyDetailTables:
    def _setup_run(self, db):
        return _insert_run(db)

    def test_spread_arb_empty(self, db):
        assert get_spread_arb_baskets(db) == []

    def test_spread_arb_inserted_and_retrieved(self, db):
        run_id = self._setup_run(db)
        db.log_spread_arb_basket(run_id, {
            "event_slug": "slug1", "title": "Test basket", "leg_count": 3,
            "total_yes_sum": 0.85, "gap_pp": 15.0, "score": 0.9,
            "days_to_close": 5, "volume": 10000.0,
            "decision": "open", "reason": "good gap",
        })
        rows = get_spread_arb_baskets(db)
        assert len(rows) == 1
        assert rows[0]["event_slug"] == "slug1"
        assert rows[0]["decision"] == "open"

    def test_spread_arb_filter_by_run_id(self, db):
        r1 = self._setup_run(db)
        r2 = self._setup_run(db)
        db.log_spread_arb_basket(r1, {"event_slug": "s1", "title": "A", "decision": "open"})
        db.log_spread_arb_basket(r2, {"event_slug": "s2", "title": "B", "decision": "skip"})
        rows = get_spread_arb_baskets(db, run_id=r1)
        assert len(rows) == 1
        assert rows[0]["event_slug"] == "s1"

    def test_resolution_hunter_inserted_and_retrieved(self, db):
        run_id = self._setup_run(db)
        db.log_resolution_hunter_check(run_id, {
            "market_slug": "mslug1", "title": "Will X happen?",
            "candidate_score": 0.8, "news_count": 5,
            "claude_confidence": 0.9, "claude_outcome": "YES",
            "decision": "open", "reason": "high conf",
        })
        rows = get_resolution_hunter_checks(db)
        assert len(rows) == 1
        assert rows[0]["market_slug"] == "mslug1"
        assert rows[0]["claude_outcome"] == "YES"

    def test_stale_market_inserted_and_retrieved(self, db):
        run_id = self._setup_run(db)
        db.log_stale_market_check(run_id, {
            "market_slug": "stale1", "title": "Stale market",
            "topic_key": "weather", "candidate_score": 0.6,
            "news_count": 3, "decision": "skip", "reason": "low score",
        })
        rows = get_stale_market_checks(db)
        assert len(rows) == 1
        assert rows[0]["topic_key"] == "weather"

    def test_correlated_pairs_inserted_and_retrieved(self, db):
        run_id = self._setup_run(db)
        db.log_correlated_pairs_check(run_id, {
            "slug_a": "a", "slug_b": "b",
            "relationship": "prerequisite", "violation_pp": 12.5,
            "chosen_slug": "a", "decision": "open", "reason": "violation",
        })
        rows = get_correlated_pairs_checks(db)
        assert len(rows) == 1
        assert rows[0]["violation_pp"] == pytest.approx(12.5)

    def test_limit_respected(self, db):
        run_id = self._setup_run(db)
        for i in range(5):
            db.log_spread_arb_basket(run_id, {"event_slug": f"s{i}", "title": f"T{i}", "decision": "open"})
        rows = get_spread_arb_baskets(db, limit=3)
        assert len(rows) == 3

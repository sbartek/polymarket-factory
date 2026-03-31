"""Reusable read-only query helpers for the factory SQLite database."""
from __future__ import annotations

from pathlib import Path

from factory.db import DB_PATH, FactoryDB


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def get_latest_runs(db: FactoryDB, n: int = 5) -> list[dict]:
    """Return the N most recent runs, newest first."""
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def get_decisions(
    db: FactoryDB,
    run_id: str | None = None,
    strategy: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return decisions, optionally filtered by run_id and/or strategy."""
    clauses: list[str] = []
    params: list = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if strategy:
        clauses.append("strategy = ?")
        params.append(strategy)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with db._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM decisions {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_decisions_summary(
    db: FactoryDB,
    run_id: str | None = None,
) -> list[dict]:
    """Return decision counts grouped by (decision_type, decision) for a run."""
    clauses: list[str] = []
    params: list = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db._connect() as conn:
        rows = conn.execute(
            f"""
            SELECT decision_type, decision, COUNT(*) AS cnt
            FROM decisions {where}
            GROUP BY decision_type, decision
            ORDER BY cnt DESC
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Strategy-specific detail tables
# ---------------------------------------------------------------------------

def _query_detail_table(
    db: FactoryDB,
    table: str,
    run_id: str | None,
    limit: int,
) -> list[dict]:
    clauses: list[str] = []
    params: list = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    with db._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_spread_arb_baskets(
    db: FactoryDB, run_id: str | None = None, limit: int = 50
) -> list[dict]:
    return _query_detail_table(db, "spread_arb_baskets", run_id, limit)


def get_resolution_hunter_checks(
    db: FactoryDB, run_id: str | None = None, limit: int = 50
) -> list[dict]:
    return _query_detail_table(db, "resolution_hunter_checks", run_id, limit)


def get_stale_market_checks(
    db: FactoryDB, run_id: str | None = None, limit: int = 50
) -> list[dict]:
    return _query_detail_table(db, "stale_market_checks", run_id, limit)


def get_correlated_pairs_checks(
    db: FactoryDB, run_id: str | None = None, limit: int = 50
) -> list[dict]:
    return _query_detail_table(db, "correlated_pairs_checks", run_id, limit)


DETAIL_TABLE_GETTERS = {
    "spread_arb": get_spread_arb_baskets,
    "resolution_hunter": get_resolution_hunter_checks,
    "stale_market": get_stale_market_checks,
    "correlated_pairs": get_correlated_pairs_checks,
}


# ---------------------------------------------------------------------------
# Open positions
# ---------------------------------------------------------------------------

def get_open_positions(
    db: FactoryDB,
    strategy: str | None = None,
    time_window: str | None = None,
) -> list[dict]:
    """Return open trades, optionally filtered. Ordered by opened_at ASC (oldest first)."""
    clauses = ["status = 'open'"]
    params: list = []
    if strategy:
        clauses.append("strategy = ?")
        params.append(strategy)
    if time_window:
        clauses.append("time_window = ?")
        params.append(time_window)
    where = "WHERE " + " AND ".join(clauses)
    with db._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM trades {where} ORDER BY opened_at ASC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def open_db(path: Path | None = None) -> FactoryDB:
    """Open the factory DB from an optional override path."""
    return FactoryDB(path=path or DB_PATH)

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


def get_correlated_laggard_checks(
    db: FactoryDB, run_id: str | None = None, limit: int = 50
) -> list[dict]:
    return _query_detail_table(db, "correlated_laggard_checks", run_id, limit)


def get_esport48_checks(
    db: FactoryDB, run_id: str | None = None, limit: int = 50
) -> list[dict]:
    return _query_detail_table(db, "esport48_checks", run_id, limit)


DETAIL_TABLE_GETTERS = {
    "spread_arb": get_spread_arb_baskets,
    "resolution_hunter": get_resolution_hunter_checks,
    "stale_market": get_stale_market_checks,
    "correlated_pairs": get_correlated_pairs_checks,
    "correlated_laggard": get_correlated_laggard_checks,
    "esport48": get_esport48_checks,
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


def get_legacy_open_positions(db: FactoryDB, strategy: str | None = None) -> list[dict]:
    """Return open legacy trades, oldest first."""
    clauses = ["status = 'open'", "(lifecycle_group = 'legacy' OR strategy NOT IN (?, ?, ?, ?, ?, ?, ?))"]
    params: list = ["ev_news", "spread_arb", "resolution_hunter", "stale_market", "correlated_pairs", "correlated_laggard", "esport48"]
    if strategy:
        clauses.append("strategy = ?")
        params.append(strategy)
    where = "WHERE " + " AND ".join(clauses)
    with db._connect() as conn:
        rows = conn.execute(f"SELECT * FROM trades {where} ORDER BY opened_at ASC", params).fetchall()
    return [dict(r) for r in rows]


def get_run_analytics(db: FactoryDB, limit_runs: int = 20) -> dict:
    """Aggregate recent run and decision data for operator analytics."""
    runs = get_latest_runs(db, n=limit_runs)
    run_ids = [r["id"] for r in runs]
    if not run_ids:
        return {
            "runs": [],
            "status_counts": {},
            "mode_counts": {},
            "decision_reason_counts": [],
            "opens_by_strategy": [],
            "skips_by_strategy": [],
        }

    placeholders = ",".join("?" for _ in run_ids)
    with db._connect() as conn:
        decision_reason_counts = [dict(r) for r in conn.execute(
            f"SELECT COALESCE(reason, decision_type) AS reason, COUNT(*) AS cnt FROM decisions WHERE run_id IN ({placeholders}) GROUP BY COALESCE(reason, decision_type) ORDER BY cnt DESC LIMIT 12",
            run_ids,
        ).fetchall()]
        opens_by_strategy = [dict(r) for r in conn.execute(
            f"SELECT strategy, COUNT(*) AS cnt FROM decisions WHERE run_id IN ({placeholders}) AND decision IN ('open','dry_open') GROUP BY strategy ORDER BY cnt DESC",
            run_ids,
        ).fetchall()]
        skips_by_strategy = [dict(r) for r in conn.execute(
            f"SELECT strategy, COUNT(*) AS cnt FROM decisions WHERE run_id IN ({placeholders}) AND decision = 'skip' GROUP BY strategy ORDER BY cnt DESC",
            run_ids,
        ).fetchall()]

    status_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    for r in runs:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        mode_counts[r["mode"]] = mode_counts.get(r["mode"], 0) + 1

    return {
        "runs": runs,
        "status_counts": status_counts,
        "mode_counts": mode_counts,
        "decision_reason_counts": decision_reason_counts,
        "opens_by_strategy": opens_by_strategy,
        "skips_by_strategy": skips_by_strategy,
    }


def open_db(path: Path | None = None) -> FactoryDB:
    """Open the factory DB from an optional override path."""
    return FactoryDB(path=path or DB_PATH)

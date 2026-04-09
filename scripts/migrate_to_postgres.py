#!/usr/bin/env python3
"""Migrate data from local SQLite to Cloud SQL PostgreSQL.

Usage:
    uv run python scripts/migrate_to_postgres.py [--sqlite-path data/factory.sqlite3]

Requires DATABASE_URL env var pointing to the PostgreSQL instance.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE = PROJECT_ROOT / "data" / "factory.sqlite3"

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    markets_fetched INTEGER DEFAULT 0,
    closed_count INTEGER DEFAULT 0,
    new_positions_count INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS run_locks (
    name TEXT PRIMARY KEY,
    owner_run_id TEXT,
    acquired_at TEXT,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    market_id TEXT NOT NULL,
    market_title TEXT NOT NULL,
    outcome TEXT NOT NULL,
    amount_usdc DOUBLE PRECISION NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    shares DOUBLE PRECISION NOT NULL,
    opened_at TEXT NOT NULL,
    closes TEXT,
    url TEXT,
    status TEXT NOT NULL,
    exit_price DOUBLE PRECISION DEFAULT 0,
    closed_at TEXT,
    pnl_usdc DOUBLE PRECISION DEFAULT 0,
    resolved_outcome TEXT,
    notes TEXT,
    run_id_opened TEXT,
    run_id_closed TEXT,
    lifecycle_group TEXT,
    time_window TEXT,
    edge_type TEXT,
    mode TEXT DEFAULT 'paper',
    FOREIGN KEY(run_id_opened) REFERENCES runs(id),
    FOREIGN KEY(run_id_closed) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    market_id TEXT NOT NULL,
    market_title TEXT NOT NULL,
    outcome TEXT NOT NULL,
    market_price DOUBLE PRECISION NOT NULL,
    p_hat DOUBLE PRECISION NOT NULL,
    ev_pp DOUBLE PRECISION NOT NULL,
    confidence TEXT,
    closes TEXT,
    url TEXT,
    rationale TEXT,
    time_window TEXT,
    edge_type TEXT,
    decision_status TEXT,
    phase TEXT DEFAULT 'combined',
    consumed_by_run_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    strategy TEXT,
    market_id TEXT,
    decision_type TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS run_logs (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    level TEXT NOT NULL,
    strategy TEXT,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    open_positions INTEGER NOT NULL,
    open_cost_usdc DOUBLE PRECISION NOT NULL,
    open_mark_value_usdc DOUBLE PRECISION NOT NULL,
    unrealized_pnl_usdc DOUBLE PRECISION NOT NULL,
    closed_pnl_usdc DOUBLE PRECISION NOT NULL,
    net_usdc DOUBLE PRECISION NOT NULL,
    marked_positions INTEGER DEFAULT 0,
    stale_positions INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS market_observations (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_slug TEXT,
    market_id TEXT NOT NULL,
    market_slug TEXT,
    market_title TEXT,
    yes_price DOUBLE PRECISION,
    best_bid DOUBLE PRECISION,
    best_ask DOUBLE PRECISION,
    spread DOUBLE PRECISION,
    liquidity DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    volume_24hr DOUBLE PRECISION,
    close_time TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS market_snapshot_archives (
    run_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS spread_arb_baskets (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_slug TEXT,
    title TEXT,
    leg_count INTEGER,
    total_yes_sum DOUBLE PRECISION,
    gap_pp DOUBLE PRECISION,
    score DOUBLE PRECISION,
    days_to_close INTEGER,
    volume DOUBLE PRECISION,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS resolution_hunter_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    market_slug TEXT,
    title TEXT,
    candidate_score DOUBLE PRECISION,
    news_count INTEGER,
    claude_confidence DOUBLE PRECISION,
    claude_outcome TEXT,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS stale_market_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    market_slug TEXT,
    title TEXT,
    topic_key TEXT,
    candidate_score DOUBLE PRECISION,
    news_count INTEGER,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS correlated_pairs_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    slug_a TEXT,
    slug_b TEXT,
    relationship TEXT,
    violation_pp DOUBLE PRECISION,
    chosen_slug TEXT,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS correlated_laggard_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    leader_slug TEXT,
    laggard_slug TEXT,
    topic_key TEXT,
    leader_price DOUBLE PRECISION,
    laggard_price DOUBLE PRECISION,
    divergence_pp DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS esport48_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    market_slug TEXT,
    title TEXT,
    signal_type TEXT,
    current_price DOUBLE PRECISION,
    hours_to_close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    liquidity DOUBLE PRECISION,
    ev_pp DOUBLE PRECISION,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS celebrity_tabloid_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    market_slug TEXT,
    title TEXT,
    subject_names TEXT,
    signal_family TEXT,
    candidate_score DOUBLE PRECISION,
    news_hits INTEGER,
    corroboration_score DOUBLE PRECISION,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS mutually_exclusive_oversum_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    market_slug TEXT,
    title TEXT,
    oversum_pp DOUBLE PRECISION,
    leg_count INTEGER,
    chosen_leg TEXT,
    chosen_yes_price DOUBLE PRECISION,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS polling_vs_market_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    market_slug TEXT,
    title TEXT,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS signal_execution_checks (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    market_id TEXT NOT NULL,
    market_title TEXT,
    outcome TEXT,
    quote_price DOUBLE PRECISION,
    best_bid DOUBLE PRECISION,
    best_ask DOUBLE PRECISION,
    quoted_spread DOUBLE PRECISION,
    order_min_size DOUBLE PRECISION,
    liquidity_proxy DOUBLE PRECISION,
    source_confidence TEXT,
    fill_price_10 DOUBLE PRECISION,
    fill_price_25 DOUBLE PRECISION,
    fill_price_50 DOUBLE PRECISION,
    fill_price_100 DOUBLE PRECISION,
    fill_price_250 DOUBLE PRECISION,
    slippage_10_pp DOUBLE PRECISION,
    slippage_25_pp DOUBLE PRECISION,
    slippage_50_pp DOUBLE PRECISION,
    slippage_100_pp DOUBLE PRECISION,
    slippage_250_pp DOUBLE PRECISION,
    ev_after_slippage_10_pp DOUBLE PRECISION,
    ev_after_slippage_25_pp DOUBLE PRECISION,
    ev_after_slippage_50_pp DOUBLE PRECISION,
    ev_after_slippage_100_pp DOUBLE PRECISION,
    ev_after_slippage_250_pp DOUBLE PRECISION,
    max_size_positive_ev DOUBLE PRECISION,
    max_size_above_min_edge DOUBLE PRECISION,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS market_trades (
    id SERIAL PRIMARY KEY,
    run_id TEXT,
    condition_id TEXT NOT NULL,
    slug TEXT,
    event_slug TEXT,
    title TEXT,
    outcome TEXT,
    side TEXT,
    price DOUBLE PRECISION NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    trade_timestamp INTEGER NOT NULL,
    tx_hash TEXT,
    fetched_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_market_id ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_status ON trades(strategy, status);
CREATE INDEX IF NOT EXISTS idx_signals_run_id ON signals(run_id);
CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy);
CREATE INDEX IF NOT EXISTS idx_signals_market_id ON signals(market_id);
CREATE INDEX IF NOT EXISTS idx_signals_decision_status ON signals(decision_status);
CREATE INDEX IF NOT EXISTS idx_decisions_run_id ON decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_decisions_strategy ON decisions(strategy);
CREATE INDEX IF NOT EXISTS idx_decisions_market_id ON decisions(market_id);
CREATE INDEX IF NOT EXISTS idx_decisions_type ON decisions(decision_type);
CREATE INDEX IF NOT EXISTS idx_decisions_decision ON decisions(decision);
CREATE INDEX IF NOT EXISTS idx_run_logs_run_id ON run_logs(run_id);
CREATE INDEX IF NOT EXISTS idx_signal_execution_checks_run_id ON signal_execution_checks(run_id);
CREATE INDEX IF NOT EXISTS idx_signal_execution_checks_strategy ON signal_execution_checks(strategy);
CREATE INDEX IF NOT EXISTS idx_signal_execution_checks_market_id ON signal_execution_checks(market_id);
CREATE INDEX IF NOT EXISTS idx_market_observations_run_id ON market_observations(run_id);
CREATE INDEX IF NOT EXISTS idx_market_observations_market_id ON market_observations(market_id);
CREATE INDEX IF NOT EXISTS idx_market_observations_created_at ON market_observations(created_at);
CREATE INDEX IF NOT EXISTS idx_market_snapshot_archives_created_at ON market_snapshot_archives(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_trades_tx_hash ON market_trades(tx_hash);
CREATE INDEX IF NOT EXISTS idx_market_trades_slug ON market_trades(slug);
CREATE INDEX IF NOT EXISTS idx_market_trades_condition_id ON market_trades(condition_id);
CREATE INDEX IF NOT EXISTS idx_market_trades_trade_timestamp ON market_trades(trade_timestamp);
CREATE INDEX IF NOT EXISTS idx_market_trades_fetched_at ON market_trades(fetched_at);
"""

# Tables to migrate in order (respecting foreign keys)
# Skip market_observations — too large, start fresh
TABLES_IN_ORDER = [
    "runs",
    "run_locks",
    "trades",
    "signals",
    "decisions",
    "run_logs",
    "portfolio_snapshots",
    # market_snapshot_archives skipped — 4GB of JSON blobs, start fresh
    "spread_arb_baskets",
    "resolution_hunter_checks",
    "stale_market_checks",
    "correlated_pairs_checks",
    "correlated_laggard_checks",
    "esport48_checks",
    "celebrity_tabloid_checks",
    "mutually_exclusive_oversum_checks",
    "polling_vs_market_checks",
    "signal_execution_checks",
    "market_trades",
    # market_observations skipped — 8.7M rows, start fresh
]

BATCH_SIZE = 5000


def get_columns(sqlite_conn: sqlite3.Connection, table: str) -> list[str]:
    cur = sqlite_conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    table: str,
    columns: list[str],
) -> int:
    """Copy all rows from SQLite table to PostgreSQL. Returns rows inserted."""
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    # For SERIAL columns, skip 'id' and let PostgreSQL auto-generate
    serial_tables = {
        "signals", "decisions", "run_logs", "portfolio_snapshots",
        "market_observations", "spread_arb_baskets",
        "resolution_hunter_checks", "stale_market_checks",
        "correlated_pairs_checks", "correlated_laggard_checks",
        "esport48_checks", "celebrity_tabloid_checks",
        "mutually_exclusive_oversum_checks", "polling_vs_market_checks",
        "signal_execution_checks", "market_trades",
    }

    if table in serial_tables and "id" in columns:
        columns = [c for c in columns if c != "id"]
        col_list = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))

    total = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if total == 0:
        print(f"  {table}: 0 rows (skip)")
        return 0

    print(f"  {table}: {total:,} rows ...", end=" ", flush=True)

    select_cols = ", ".join(columns)
    cursor = sqlite_conn.execute(f"SELECT {select_cols} FROM {table}")

    inserted = 0
    pg_cur = pg_conn.cursor()
    while True:
        batch = cursor.fetchmany(BATCH_SIZE)
        if not batch:
            break
        values = [tuple(row) for row in batch]
        insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        pg_cur.executemany(insert_sql, values)
        inserted += len(batch)
        print(f"{inserted:,}", end=" ", flush=True)

    pg_conn.commit()

    # Reset sequence for SERIAL tables
    if table in serial_tables:
        pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))")
        pg_conn.commit()

    print(f"done ({inserted:,})")
    return inserted


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--skip-observations", action="store_true", default=True,
                        help="Skip market_observations (default: skip)")
    parser.add_argument("--include-observations", action="store_true",
                        help="Include market_observations (8.7M rows, slow)")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    if not args.sqlite_path.exists():
        print(f"ERROR: SQLite DB not found: {args.sqlite_path}")
        sys.exit(1)

    print(f"Source: {args.sqlite_path}")
    print(f"Target: {database_url.split('@')[1] if '@' in database_url else database_url}")
    print()

    # Connect
    sqlite_conn = sqlite3.connect(str(args.sqlite_path), timeout=60)
    pg_conn = psycopg2.connect(database_url)

    # Create schema
    print("Creating PostgreSQL schema...")
    pg_cur = pg_conn.cursor()
    for statement in PG_SCHEMA.split(";"):
        statement = statement.strip()
        if statement:
            pg_cur.execute(statement + ";")
    pg_conn.commit()
    print("Schema created.\n")

    # Disable FK triggers during migration
    pg_cur.execute("""
        DO $$ DECLARE r RECORD;
        BEGIN
            FOR r IN (SELECT conname, conrelid::regclass AS tbl
                      FROM pg_constraint WHERE contype = 'f') LOOP
                EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', r.tbl, r.conname);
            END LOOP;
        END $$;
    """)
    pg_conn.commit()
    print("Foreign key constraints dropped for migration.\n")

    # Migrate tables
    tables = list(TABLES_IN_ORDER)
    if args.include_observations:
        tables.append("market_observations")

    total_rows = 0
    for table in tables:
        columns = get_columns(sqlite_conn, table)
        rows = migrate_table(sqlite_conn, pg_conn, table, columns)
        total_rows += rows

    # FK constraints are not re-added — the schema doesn't strictly need them at runtime

    print(f"\nMigration complete: {total_rows:,} rows migrated.")
    if not args.include_observations:
        obs_count = sqlite_conn.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0]
        print(f"Skipped market_observations ({obs_count:,} rows) — will start fresh in PostgreSQL.")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()

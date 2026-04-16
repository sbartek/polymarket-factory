"""PostgreSQL persistence for runs, trades, signals, decisions, logs, and strategy detail rows."""
from __future__ import annotations

import contextlib
import csv
import json
import os
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

from .strategy_meta import ACTIVE_STRATEGIES, strategy_metadata

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PATH = Path(__file__).parents[1] / "data" / "factory.sqlite3"  # legacy, kept for backup script
TRADES_CSV = Path(__file__).parents[1] / "data" / "trades.csv"
TRADE_FIELDS = [
    "id", "strategy", "market_id", "market_title", "outcome",
    "amount_usdc", "entry_price", "shares", "opened_at", "closes", "url",
    "status", "exit_price", "closed_at", "pnl_usdc", "resolved_outcome", "notes", "mode",
]
RETENTION_CLEANUP_TABLES = [
    "market_snapshot_archives",
    "market_observations",
    "signals",
    "decisions",
    "run_logs",
    "portfolio_snapshots",
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
]
RETENTION_TIMESTAMP_COLS = {"market_trades": "fetched_at"}


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def utcnow_plus_seconds(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


SCHEMA_SQL = """
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
    amount_usdc REAL NOT NULL,
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    opened_at TEXT NOT NULL,
    closes TEXT,
    url TEXT,
    status TEXT NOT NULL,
    exit_price REAL DEFAULT 0,
    closed_at TEXT,
    pnl_usdc REAL DEFAULT 0,
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
    market_price REAL NOT NULL,
    p_hat REAL NOT NULL,
    ev_pp REAL NOT NULL,
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
    open_cost_usdc REAL NOT NULL,
    open_mark_value_usdc REAL NOT NULL,
    unrealized_pnl_usdc REAL NOT NULL,
    closed_pnl_usdc REAL NOT NULL,
    net_usdc REAL NOT NULL,
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
    yes_price REAL,
    best_bid REAL,
    best_ask REAL,
    spread REAL,
    liquidity REAL,
    volume REAL,
    volume_24hr REAL,
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
    total_yes_sum REAL,
    gap_pp REAL,
    score REAL,
    days_to_close INTEGER,
    volume REAL,
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
    candidate_score REAL,
    news_count INTEGER,
    claude_confidence REAL,
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
    candidate_score REAL,
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
    violation_pp REAL,
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
    leader_price REAL,
    laggard_price REAL,
    divergence_pp REAL,
    volume_ratio REAL,
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
    current_price REAL,
    hours_to_close REAL,
    volume REAL,
    liquidity REAL,
    ev_pp REAL,
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
    candidate_score REAL,
    news_hits INTEGER,
    corroboration_score REAL,
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
    oversum_pp REAL,
    leg_count INTEGER,
    chosen_leg TEXT,
    chosen_yes_price REAL,
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
    quote_price REAL,
    best_bid REAL,
    best_ask REAL,
    quoted_spread REAL,
    order_min_size REAL,
    liquidity_proxy REAL,
    source_confidence TEXT,
    fill_price_10 REAL,
    fill_price_25 REAL,
    fill_price_50 REAL,
    fill_price_100 REAL,
    fill_price_250 REAL,
    slippage_10_pp REAL,
    slippage_25_pp REAL,
    slippage_50_pp REAL,
    slippage_100_pp REAL,
    slippage_250_pp REAL,
    ev_after_slippage_10_pp REAL,
    ev_after_slippage_25_pp REAL,
    ev_after_slippage_50_pp REAL,
    ev_after_slippage_100_pp REAL,
    ev_after_slippage_250_pp REAL,
    max_size_positive_ev REAL,
    max_size_above_min_edge REAL,
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
    price REAL NOT NULL,
    size REAL NOT NULL,
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

SQLITE_SCHEMA_SQL = (
    "PRAGMA journal_mode=WAL;\n\n"
    + re.sub(r"\bid SERIAL PRIMARY KEY\b", "id INTEGER PRIMARY KEY AUTOINCREMENT", SCHEMA_SQL)
)


class _SQLiteCursorCompat:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def execute(self, sql, params=()):
        self._cursor.execute(sql.replace("%s", "?"), params)
        return self

    def executemany(self, sql, seq_of_params):
        self._cursor.executemany(sql.replace("%s", "?"), seq_of_params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        if size is None:
            return self._cursor.fetchmany()
        return self._cursor.fetchmany(size)

    @property
    def rowcount(self):
        return self._cursor.rowcount


class FactoryDB:
    def __init__(self, dsn: str | None = None, path: Path | None = None):
        self.path = Path(path) if path is not None else None
        self.sqlite_mode = self.path is not None
        self.dsn = None if self.sqlite_mode else (dsn or DATABASE_URL)
        if self.sqlite_mode:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.dsn:
            raise RuntimeError("DATABASE_URL not set and no dsn provided")
        self._init_db()

    def _connect(self):
        """Return a sqlite3-compatible connection for legacy code using conn.execute() and ? placeholders."""
        if self.sqlite_mode:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            return conn
        from .pg_compat import CompatConnection
        return CompatConnection(self.dsn)

    def _raw_connect(self):
        if self.sqlite_mode:
            return self._connect()
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = False
        return conn

    @contextlib.contextmanager
    def _conn(self):
        """Context manager that yields (conn, cur) with DictCursor, commits on success, rolls back on error."""
        if self.sqlite_mode:
            conn = self._connect()
            try:
                yield conn, _SQLiteCursorCompat(conn.cursor())
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        conn = self._raw_connect()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            yield conn, cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        if self.sqlite_mode:
            with self._connect() as conn:
                conn.executescript(SQLITE_SCHEMA_SQL)
                conn.commit()
            self._migrate_db()
            return
        with self._conn() as (conn, cur):
            for statement in SCHEMA_SQL.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement + ";")
        self._migrate_db()

    def _migrate_db(self):
        migrations = [
            "ALTER TABLE trades ADD COLUMN mode TEXT DEFAULT 'paper'",
            "ALTER TABLE signals ADD COLUMN phase TEXT DEFAULT 'combined'",
            "ALTER TABLE signals ADD COLUMN consumed_by_run_id TEXT",
        ]
        if self.sqlite_mode:
            with self._connect() as conn:
                for sql in migrations:
                    try:
                        conn.execute(sql)
                        conn.commit()
                    except sqlite3.OperationalError as e:
                        text = str(e).lower()
                        if "duplicate column" not in text and "already exists" not in text:
                            raise
            return
        conn = self._raw_connect()
        try:
            cur = conn.cursor()
            for sql in migrations:
                try:
                    cur.execute(sql)
                    conn.commit()
                except psycopg2.errors.DuplicateColumn:
                    conn.rollback()
                except Exception as e:
                    conn.rollback()
                    if "already exists" not in str(e):
                        raise
        finally:
            conn.close()

    def acquire_run_lock(self, name: str, owner_run_id: str, ttl_seconds: int = 7200) -> bool:
        now = utcnow()
        expires = utcnow_plus_seconds(ttl_seconds)
        if self.sqlite_mode:
            conn = self._connect()
            try:
                conn.execute("BEGIN EXCLUSIVE")
                row = conn.execute("SELECT owner_run_id, expires_at FROM run_locks WHERE name = ?", (name,)).fetchone()
                if row and row["expires_at"] and row["expires_at"] > now and row["owner_run_id"] != owner_run_id:
                    conn.rollback()
                    return False
                conn.execute(
                    "INSERT INTO run_locks (name, owner_run_id, acquired_at, expires_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET owner_run_id=excluded.owner_run_id, acquired_at=excluded.acquired_at, expires_at=excluded.expires_at",
                    (name, owner_run_id, now, expires),
                )
                conn.commit()
                return True
            except sqlite3.OperationalError:
                with contextlib.suppress(Exception):
                    conn.rollback()
                return False
            finally:
                conn.close()
        conn = self._raw_connect()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("SELECT owner_run_id, expires_at FROM run_locks WHERE name = %s FOR UPDATE", (name,))
            row = cur.fetchone()
            if row and row["expires_at"] and row["expires_at"] > now and row["owner_run_id"] != owner_run_id:
                conn.rollback()
                return False
            cur.execute(
                "INSERT INTO run_locks (name, owner_run_id, acquired_at, expires_at) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT(name) DO UPDATE SET owner_run_id=EXCLUDED.owner_run_id, acquired_at=EXCLUDED.acquired_at, expires_at=EXCLUDED.expires_at",
                (name, owner_run_id, now, expires),
            )
            conn.commit()
            return True
        except psycopg2.OperationalError:
            with contextlib.suppress(Exception):
                conn.rollback()
            return False
        finally:
            conn.close()

    def release_run_lock(self, name: str, owner_run_id: str):
        with self._conn() as (conn, cur):
            cur.execute("DELETE FROM run_locks WHERE name = %s AND owner_run_id = %s", (name, owner_run_id))

    def ensure_trades_imported_from_csv(self, csv_path: Path | None = None) -> int:
        csv_path = csv_path or TRADES_CSV
        with self._conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM trades")
            existing = cur.fetchone()[0]
            if existing > 0 or not csv_path.exists():
                return 0
            rows = list(csv.DictReader(open(csv_path, newline="")))
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO trades (
                        id, strategy, market_id, market_title, outcome, amount_usdc, entry_price,
                        shares, opened_at, closes, url, status, exit_price, closed_at,
                        pnl_usdc, resolved_outcome, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        row.get("id", ""), row.get("strategy", ""), row.get("market_id", ""), row.get("market_title", ""),
                        row.get("outcome", ""), float(row.get("amount_usdc") or 0), float(row.get("entry_price") or 0),
                        float(row.get("shares") or 0), row.get("opened_at", ""), row.get("closes", ""), row.get("url", ""),
                        row.get("status", "open"), float(row.get("exit_price") or 0), row.get("closed_at", ""),
                        float(row.get("pnl_usdc") or 0), row.get("resolved_outcome", ""), row.get("notes", ""),
                    ),
                )
            return len(rows)

    def load_trades(self, mode: str | None = None) -> list[dict]:
        with self._conn() as (conn, cur):
            if mode == "paper":
                cur.execute(
                    "SELECT * FROM trades WHERE COALESCE(NULLIF(mode, ''), 'paper') = 'paper' ORDER BY opened_at, id"
                )
            elif mode:
                cur.execute(
                    "SELECT * FROM trades WHERE mode = %s ORDER BY opened_at, id",
                    (mode,),
                )
            else:
                cur.execute("SELECT * FROM trades ORDER BY opened_at, id")
            return [dict(r) for r in cur.fetchall()]

    def has_open_position(self, market_id: str, strategy: str, mode: str | None = None) -> bool:
        # Normalize: match both bare numeric ("1940777") and composite ("slug:1940777")
        numeric_id = market_id.split(":")[-1] if ":" in market_id else market_id
        like_suffix = f"%:{numeric_id}"
        with self._conn() as (conn, cur):
            id_clause = "(market_id = %s OR market_id = %s OR market_id LIKE %s)"
            id_params = [market_id, numeric_id, like_suffix]
            if mode == "paper":
                cur.execute(
                    f"SELECT 1 FROM trades WHERE {id_clause} AND strategy = %s AND status = 'open' AND COALESCE(NULLIF(mode, ''), 'paper') = 'paper' LIMIT 1",
                    (*id_params, strategy),
                )
            elif mode:
                cur.execute(f"SELECT 1 FROM trades WHERE {id_clause} AND strategy = %s AND status = 'open' AND mode = %s LIMIT 1", (*id_params, strategy, mode))
            else:
                cur.execute(f"SELECT 1 FROM trades WHERE {id_clause} AND strategy = %s AND status = 'open' LIMIT 1", (*id_params, strategy))
            return cur.fetchone() is not None

    def insert_trade(self, trade: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                """
                INSERT INTO trades (
                    id, strategy, market_id, market_title, outcome, amount_usdc, entry_price,
                    shares, opened_at, closes, url, status, exit_price, closed_at,
                    pnl_usdc, resolved_outcome, notes, run_id_opened, run_id_closed,
                    lifecycle_group, time_window, edge_type, mode
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    trade.get("id", ""), trade.get("strategy", ""), trade.get("market_id", ""), trade.get("market_title", ""),
                    trade.get("outcome", ""), float(trade.get("amount_usdc") or 0), float(trade.get("entry_price") or 0),
                    float(trade.get("shares") or 0), trade.get("opened_at", ""), trade.get("closes", ""), trade.get("url", ""),
                    trade.get("status", "open"), float(trade.get("exit_price") or 0), trade.get("closed_at", ""),
                    float(trade.get("pnl_usdc") or 0), trade.get("resolved_outcome", ""), trade.get("notes", ""),
                    trade.get("run_id_opened"), trade.get("run_id_closed"), trade.get("lifecycle_group"),
                    trade.get("time_window"), trade.get("edge_type"), trade.get("mode", "paper"),
                ),
            )

    def close_trade(self, trade_id: str, resolved_outcome: str, run_id_closed: str | None = None) -> bool:
        with self._conn() as (conn, cur):
            cur.execute("SELECT * FROM trades WHERE id = %s AND status = 'open'", (trade_id,))
            row = cur.fetchone()
            if not row:
                return False
            t = dict(row)
            outcome = resolved_outcome.upper()
            shares = float(t["shares"])
            amount = float(t["amount_usdc"])
            if t.get("outcome") == "FULL_SET" or outcome == "CANCELLED":
                pnl = 0.0
            else:
                pnl = shares * 1.0 - amount if outcome == t["outcome"] else -amount
            cur.execute(
                "UPDATE trades SET status='closed', exit_price=%s, closed_at=%s, pnl_usdc=%s, resolved_outcome=%s, run_id_closed=%s WHERE id=%s",
                (1.0 if outcome == t["outcome"] else 0.0, datetime.now().isoformat(timespec="seconds"), round(pnl, 4), resolved_outcome, run_id_closed, trade_id),
            )
            return True

    def backfill_trade_metadata(self) -> int:
        meta = strategy_metadata()
        updated = 0
        with self._conn() as (conn, cur):
            cur.execute("SELECT id, strategy, lifecycle_group, time_window, edge_type FROM trades")
            rows = cur.fetchall()
            for row in rows:
                trade = dict(row)
                strategy = trade.get("strategy")
                strategy_meta = meta.get(strategy, {})
                lifecycle_group = trade.get("lifecycle_group") or ("active" if strategy in ACTIVE_STRATEGIES else "legacy")
                time_window = trade.get("time_window") or strategy_meta.get("time_window")
                edge_type = trade.get("edge_type") or strategy_meta.get("edge_type")

                if trade.get("lifecycle_group") and trade.get("time_window") and trade.get("edge_type"):
                    continue

                cur.execute(
                    "UPDATE trades SET lifecycle_group = %s, time_window = %s, edge_type = %s WHERE id = %s",
                    (lifecycle_group, time_window, edge_type, trade["id"]),
                )
                updated += 1
        return updated

    def start_run(self, mode: str, notes: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._conn() as (conn, cur):
            cur.execute("INSERT INTO runs (id, started_at, mode, status, notes) VALUES (%s, %s, %s, %s, %s)", (run_id, utcnow(), mode, "running", notes))
        return run_id

    def finish_run(self, run_id: str, status: str, markets_fetched: int = 0, closed_count: int = 0, new_positions_count: int = 0, notes: str | None = None):
        with self._conn() as (conn, cur):
            cur.execute(
                "UPDATE runs SET finished_at=%s, status=%s, markets_fetched=%s, closed_count=%s, new_positions_count=%s, notes=COALESCE(%s, notes) WHERE id=%s",
                (utcnow(), status, markets_fetched, closed_count, new_positions_count, notes, run_id),
            )

    def log_signal(self, run_id: str, strategy: str, signal: dict, time_window: str | None = None, edge_type: str | None = None, decision_status: str | None = None, phase: str = "combined"):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO signals (run_id, strategy, market_id, market_title, outcome, market_price, p_hat, ev_pp, confidence, closes, url, rationale, time_window, edge_type, decision_status, phase, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, strategy, signal.get("market_id", ""), signal.get("market_title", ""), signal.get("outcome", ""), float(signal.get("market_price", 0) or 0), float(signal.get("p_hat", 0) or 0), float(signal.get("ev_pp", 0) or 0), signal.get("confidence", ""), signal.get("closes", ""), signal.get("url", ""), signal.get("rationale", ""), time_window, edge_type, decision_status, phase, utcnow()),
            )

    def get_unconsumed_signals(self, max_age_hours: float = 2.0) -> list[dict]:
        """Fetch signals from a scan phase that haven't been consumed yet, deduped by (strategy, market_id, outcome)."""
        cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
        with self._conn() as (conn, cur):
            cur.execute(
                """
                SELECT s.* FROM signals s
                INNER JOIN (
                    SELECT strategy, market_id, outcome, MAX(id) AS max_id
                    FROM signals
                    WHERE phase = 'scan'
                      AND consumed_by_run_id IS NULL
                      AND created_at >= %s
                    GROUP BY strategy, market_id, outcome
                ) latest ON s.id = latest.max_id
                ORDER BY s.ev_pp DESC
                """,
                (cutoff,),
            )
            return [dict(r) for r in cur.fetchall()]

    def has_recent_signal(self, strategy: str, market_id: str, hours: float = 24.0, consumed_only: bool = False) -> bool:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
        # Normalize: match both bare numeric and composite slug:numeric
        numeric_id = market_id.split(":")[-1] if ":" in market_id else market_id
        like_suffix = f"%:{numeric_id}"
        id_clause = "(market_id = %s OR market_id = %s OR market_id LIKE %s)"
        id_params = [market_id, numeric_id, like_suffix]
        with self._conn() as (conn, cur):
            if consumed_only:
                cur.execute(
                    f"SELECT 1 FROM signals WHERE strategy = %s AND {id_clause} AND created_at >= %s AND consumed_by_run_id IS NOT NULL LIMIT 1",
                    (strategy, *id_params, cutoff),
                )
            else:
                cur.execute(
                    f"SELECT 1 FROM signals WHERE strategy = %s AND {id_clause} AND created_at >= %s LIMIT 1",
                    (strategy, *id_params, cutoff),
                )
            return cur.fetchone() is not None

    def mark_signals_consumed(self, signal_ids: list[int], run_id: str):
        if not signal_ids:
            return
        if self.sqlite_mode:
            placeholders = ",".join("?" for _ in signal_ids)
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE signals SET consumed_by_run_id = ? WHERE id IN ({placeholders})",
                    (run_id, *signal_ids),
                )
                conn.commit()
            return
        with self._conn() as (conn, cur):
            cur.execute(
                "UPDATE signals SET consumed_by_run_id = %s WHERE id = ANY(%s)",
                (run_id, signal_ids),
            )

    def get_recent_price_moves(self, min_move: float = 0.15, max_hours: float = 6.0) -> list[dict]:
        """Find markets where yes_price moved significantly between the two most recent observations."""
        cutoff = (datetime.now(UTC) - timedelta(hours=max_hours)).isoformat(timespec="seconds")
        query = """
            WITH ranked AS (
                SELECT market_id, market_slug, market_title, yes_price, volume, volume_24hr,
                       close_time, created_at,
                       ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY created_at DESC) as rn
                FROM market_observations
                WHERE yes_price IS NOT NULL AND created_at >= %s
            )
            SELECT
                cur.market_id, cur.market_slug, cur.market_title,
                cur.yes_price AS cur_price, prev.yes_price AS prev_price,
                cur.yes_price - prev.yes_price AS price_move,
                cur.volume, cur.volume_24hr, cur.close_time,
                cur.created_at AS cur_time, prev.created_at AS prev_time
            FROM ranked cur
            JOIN ranked prev ON cur.market_id = prev.market_id AND prev.rn = 2
            WHERE cur.rn = 1
              AND ABS(cur.yes_price - prev.yes_price) >= %s
            ORDER BY ABS(cur.yes_price - prev.yes_price) DESC
        """
        with self._conn() as (conn, cur):
            cur.execute(query, (cutoff, min_move))
            return [dict(r) for r in cur.fetchall()]

    def log_decision(self, run_id: str, decision_type: str, decision: str, strategy: str | None = None, market_id: str | None = None, reason: str | None = None, details: dict | None = None):
        with self._conn() as (conn, cur):
            cur.execute("INSERT INTO decisions (run_id, strategy, market_id, decision_type, decision, reason, details_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (run_id, strategy, market_id, decision_type, decision, reason, json.dumps(details or {}, ensure_ascii=False), utcnow()))

    def log_event(self, run_id: str, level: str, message: str, strategy: str | None = None, payload: dict | None = None):
        with self._conn() as (conn, cur):
            cur.execute("INSERT INTO run_logs (run_id, level, strategy, message, payload_json, created_at) VALUES (%s, %s, %s, %s, %s, %s)", (run_id, level, strategy, message, json.dumps(payload or {}, ensure_ascii=False), utcnow()))

    def log_portfolio_snapshot(self, run_id: str, snapshot: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO portfolio_snapshots (run_id, open_positions, open_cost_usdc, open_mark_value_usdc, unrealized_pnl_usdc, closed_pnl_usdc, net_usdc, marked_positions, stale_positions, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    int(snapshot.get("open_positions") or 0),
                    float(snapshot.get("open_cost_usdc") or 0),
                    float(snapshot.get("open_mark_value_usdc") or 0),
                    float(snapshot.get("unrealized_pnl_usdc") or 0),
                    float(snapshot.get("closed_pnl_usdc") or 0),
                    float(snapshot.get("net_usdc") or 0),
                    int(snapshot.get("marked_positions") or 0),
                    int(snapshot.get("stale_positions") or 0),
                    utcnow(),
                ),
            )

    def log_market_observations(self, run_id: str, rows: list[dict]):
        if not rows:
            return
        created_at = utcnow()
        payload = [
            (
                run_id,
                row.get("event_slug"),
                row.get("market_id"),
                row.get("market_slug"),
                row.get("market_title"),
                row.get("yes_price"),
                row.get("best_bid"),
                row.get("best_ask"),
                row.get("spread"),
                row.get("liquidity"),
                row.get("volume"),
                row.get("volume_24hr"),
                row.get("close_time"),
                created_at,
            )
            for row in rows
            if row.get("market_id")
        ]
        if not payload:
            return
        if self.sqlite_mode:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO market_observations (
                        run_id, event_slug, market_id, market_slug, market_title,
                        yes_price, best_bid, best_ask, spread, liquidity, volume, volume_24hr,
                        close_time, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                conn.commit()
            return
        with self._conn() as (conn, cur):
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO market_observations (
                    run_id, event_slug, market_id, market_slug, market_title,
                    yes_price, best_bid, best_ask, spread, liquidity, volume, volume_24hr,
                    close_time, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                payload,
                page_size=1000,
            )

    def log_market_trades(self, run_id: str, trades_data: list[dict]) -> int:
        """Insert CLOB trades, skipping duplicates by tx_hash. Returns count inserted."""
        if not trades_data:
            return 0
        fetched_at = utcnow()
        inserted = 0
        with self._conn() as (conn, cur):
            for t in trades_data:
                try:
                    cur.execute(
                        """
                        INSERT INTO market_trades (
                            run_id, condition_id, slug, event_slug, title,
                            outcome, side, price, size, trade_timestamp, tx_hash, fetched_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (tx_hash) DO NOTHING
                        """,
                        (
                            run_id,
                            t.get("conditionId", ""),
                            t.get("slug", ""),
                            t.get("eventSlug", ""),
                            t.get("title", ""),
                            t.get("outcome", ""),
                            t.get("side", ""),
                            float(t.get("price", 0)),
                            float(t.get("size", 0)),
                            int(t.get("timestamp", 0)),
                            t.get("transactionHash", ""),
                            fetched_at,
                        ),
                    )
                    inserted += 1
                except Exception as e:
                    print(f"  [db] WARNING: failed to insert market trade: {e}")
                    continue
        return inserted

    def get_latest_trade_timestamp(self) -> int:
        """Return the most recent trade_timestamp in market_trades, or 0."""
        with self._conn() as (conn, cur):
            cur.execute("SELECT MAX(trade_timestamp) AS ts FROM market_trades")
            row = cur.fetchone()
            return int(row["ts"]) if row and row["ts"] else 0

    def get_pipeline_health(self) -> list[dict]:
        """Check health of all pipelines."""
        pipelines = [
            {"name": "scanner", "mode_pattern": "paper_scan", "expected_interval_min": 150},
            {"name": "execute", "mode_pattern": "paper_execute", "expected_interval_min": 150},
            {"name": "observer", "mode_pattern": "observer", "expected_interval_min": 45},
            {"name": "trade_fetcher", "mode_pattern": "trade_fetcher", "expected_interval_min": 45},
        ]
        results = []
        with self._conn() as (conn, cur):
            for p in pipelines:
                cur.execute(
                    "SELECT finished_at, status FROM runs WHERE mode = %s AND finished_at IS NOT NULL ORDER BY started_at DESC LIMIT 1",
                    (p["mode_pattern"],),
                )
                row = cur.fetchone()
                if not row:
                    results.append({
                        "name": p["name"], "last_run": None, "status": "never_run",
                        "age_minutes": None, "overdue": True,
                    })
                    continue
                finished = datetime.fromisoformat(row["finished_at"])
                age_min = (datetime.now(UTC) - finished).total_seconds() / 60
                results.append({
                    "name": p["name"],
                    "last_run": row["finished_at"],
                    "status": row["status"],
                    "age_minutes": round(age_min),
                    "overdue": age_min > p["expected_interval_min"],
                })
        return results

    def get_trade_volume_by_slug(self, slug: str, since_hours: float = 24.0) -> dict:
        """Aggregate trade volume and count for a market slug in the last N hours."""
        since_ts = int((datetime.now(UTC) - timedelta(hours=since_hours)).timestamp())
        with self._conn() as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) as trade_count,
                       COALESCE(SUM(size), 0) as total_size,
                       COALESCE(SUM(size * price), 0) as total_notional
                FROM market_trades
                WHERE slug = %s AND trade_timestamp >= %s
                """,
                (slug, since_ts),
            )
            row = cur.fetchone()
            return dict(row) if row else {"trade_count": 0, "total_size": 0, "total_notional": 0}

    def get_hourly_trade_volume(self, slug: str, hours: int = 168) -> list[dict]:
        """Hourly trade volume bucketed by hour for a market, last N hours (default 7 days)."""
        since_ts = int((datetime.now(UTC) - timedelta(hours=hours)).timestamp())
        with self._conn() as (conn, cur):
            cur.execute(
                """
                SELECT (trade_timestamp / 3600) * 3600 AS hour_ts,
                       COUNT(*) AS trade_count,
                       SUM(size) AS total_size,
                       SUM(size * price) AS total_notional,
                       AVG(price) AS avg_price
                FROM market_trades
                WHERE slug = %s AND trade_timestamp >= %s
                GROUP BY hour_ts
                ORDER BY hour_ts
                """,
                (slug, since_ts),
            )
            return [dict(r) for r in cur.fetchall()]

    def log_market_snapshot_archive(self, run_id: str, events: list[dict], source: str = "fetch_top"):
        payload_json = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
        with self._conn() as (conn, cur):
            cur.execute(
                """
                INSERT INTO market_snapshot_archives (
                    run_id, source, event_count, payload_json, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    source=EXCLUDED.source, event_count=EXCLUDED.event_count,
                    payload_json=EXCLUDED.payload_json, created_at=EXCLUDED.created_at
                """,
                (run_id, source, len(events), payload_json, utcnow()),
            )

    def get_retention_cleanup_counts(self, retention_days: int = 730) -> dict[str, int]:
        """Count rows eligible for retention cleanup without deleting them."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        result = {}
        with self._conn() as (conn, cur):
            for table in RETENTION_CLEANUP_TABLES:
                col = RETENTION_TIMESTAMP_COLS.get(table, "created_at")
                try:
                    cur.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {col} < %s",
                        (cutoff,),
                    )
                    count = cur.fetchone()[0]
                except Exception as e:
                    print(f"  [db] WARNING: get_retention_cleanup_counts failed for {table}: {e}")
                    conn.rollback()
                    count = 0
                result[f"{table}_deleted"] = int(count or 0)
        result["archives_deleted"] = result.get("market_snapshot_archives_deleted", 0)
        result["observations_deleted"] = result.get("market_observations_deleted", 0)
        return result

    def cleanup_old_snapshots(self, retention_days: int = 730) -> dict[str, int]:
        """Delete old rows from all unbounded tables (except trades which are permanent)."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        result = {}
        with self._conn() as (conn, cur):
            for table in RETENTION_CLEANUP_TABLES:
                col = RETENTION_TIMESTAMP_COLS.get(table, "created_at")
                try:
                    cur.execute(
                        f"DELETE FROM {table} WHERE {col} < %s", (cutoff,)
                    )
                    deleted = cur.rowcount
                except Exception as e:
                    print(f"  [db] WARNING: cleanup_old_snapshots failed for {table}: {e}")
                    conn.rollback()
                    deleted = 0
                result[f"{table}_deleted"] = deleted
        result["archives_deleted"] = result.get("market_snapshot_archives_deleted", 0)
        result["observations_deleted"] = result.get("market_observations_deleted", 0)
        return result

    def get_latest_portfolio_snapshot_before(self, created_at: str) -> dict | None:
        with self._conn() as (conn, cur):
            cur.execute(
                "SELECT * FROM portfolio_snapshots WHERE created_at <= %s ORDER BY created_at DESC LIMIT 1",
                (created_at,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def log_spread_arb_basket(self, run_id: str, basket: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO spread_arb_baskets (run_id, event_slug, title, leg_count, total_yes_sum, gap_pp, score, days_to_close, volume, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, basket.get("event_slug"), basket.get("title"), basket.get("leg_count"), basket.get("total_yes_sum"), basket.get("gap_pp"), basket.get("score"), basket.get("days_to_close"), basket.get("volume"), basket.get("decision"), basket.get("reason"), utcnow()),
            )

    def log_resolution_hunter_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO resolution_hunter_checks (run_id, market_slug, title, candidate_score, news_count, claude_confidence, claude_outcome, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, row.get("market_slug"), row.get("title"), row.get("candidate_score"), row.get("news_count"), row.get("claude_confidence"), row.get("claude_outcome"), row.get("decision"), row.get("reason"), utcnow()),
            )

    def log_stale_market_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO stale_market_checks (run_id, market_slug, title, topic_key, candidate_score, news_count, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, row.get("market_slug"), row.get("title"), row.get("topic_key"), row.get("candidate_score"), row.get("news_count"), row.get("decision"), row.get("reason"), utcnow()),
            )

    def log_correlated_pairs_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO correlated_pairs_checks (run_id, slug_a, slug_b, relationship, violation_pp, chosen_slug, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, row.get("slug_a"), row.get("slug_b"), row.get("relationship"), row.get("violation_pp"), row.get("chosen_slug"), row.get("decision"), row.get("reason"), utcnow()),
            )

    def log_correlated_laggard_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO correlated_laggard_checks (run_id, leader_slug, laggard_slug, topic_key, leader_price, laggard_price, divergence_pp, volume_ratio, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    row.get("leader_slug"),
                    row.get("laggard_slug"),
                    row.get("topic_key"),
                    row.get("leader_price"),
                    row.get("laggard_price"),
                    row.get("divergence_pp"),
                    row.get("volume_ratio"),
                    row.get("decision"),
                    row.get("reason"),
                    utcnow(),
                ),
            )

    def log_esport48_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO esport48_checks (run_id, market_slug, title, signal_type, current_price, hours_to_close, volume, liquidity, ev_pp, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    row.get("market_slug"),
                    row.get("title"),
                    row.get("signal_type"),
                    row.get("current_price"),
                    row.get("hours_to_close"),
                    row.get("volume"),
                    row.get("liquidity"),
                    row.get("ev_pp"),
                    row.get("decision"),
                    row.get("reason"),
                    utcnow(),
                ),
            )

    def log_celebrity_tabloid_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO celebrity_tabloid_checks (run_id, market_slug, title, subject_names, signal_family, candidate_score, news_hits, corroboration_score, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    row.get("market_slug"),
                    row.get("title"),
                    row.get("subject_names"),
                    row.get("signal_family"),
                    row.get("candidate_score"),
                    row.get("news_hits"),
                    row.get("corroboration_score"),
                    row.get("decision"),
                    row.get("reason"),
                    utcnow(),
                ),
            )

    def log_mutually_exclusive_oversum_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO mutually_exclusive_oversum_checks (run_id, market_slug, title, oversum_pp, leg_count, chosen_leg, chosen_yes_price, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    row.get("market_slug"),
                    row.get("title"),
                    row.get("oversum_pp"),
                    row.get("leg_count"),
                    row.get("chosen_leg"),
                    row.get("chosen_yes_price"),
                    row.get("decision"),
                    row.get("reason"),
                    utcnow(),
                ),
            )

    def log_polling_vs_market_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                "INSERT INTO polling_vs_market_checks (run_id, market_slug, title, decision, reason, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    row.get("market_slug"),
                    row.get("title"),
                    row.get("decision"),
                    row.get("reason"),
                    utcnow(),
                ),
            )

    def log_signal_execution_check(self, run_id: str, row: dict):
        with self._conn() as (conn, cur):
            cur.execute(
                """
                INSERT INTO signal_execution_checks (
                    run_id, strategy, market_id, market_title, outcome,
                    quote_price, best_bid, best_ask, quoted_spread, order_min_size,
                    liquidity_proxy, source_confidence,
                    fill_price_10, fill_price_25, fill_price_50, fill_price_100, fill_price_250,
                    slippage_10_pp, slippage_25_pp, slippage_50_pp, slippage_100_pp, slippage_250_pp,
                    ev_after_slippage_10_pp, ev_after_slippage_25_pp, ev_after_slippage_50_pp,
                    ev_after_slippage_100_pp, ev_after_slippage_250_pp,
                    max_size_positive_ev, max_size_above_min_edge, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    row.get("strategy"),
                    row.get("market_id"),
                    row.get("market_title"),
                    row.get("outcome"),
                    row.get("quote_price"),
                    row.get("best_bid"),
                    row.get("best_ask"),
                    row.get("quoted_spread"),
                    row.get("order_min_size"),
                    row.get("liquidity_proxy"),
                    row.get("source_confidence"),
                    row.get("fill_price_10"),
                    row.get("fill_price_25"),
                    row.get("fill_price_50"),
                    row.get("fill_price_100"),
                    row.get("fill_price_250"),
                    row.get("slippage_10_pp"),
                    row.get("slippage_25_pp"),
                    row.get("slippage_50_pp"),
                    row.get("slippage_100_pp"),
                    row.get("slippage_250_pp"),
                    row.get("ev_after_slippage_10_pp"),
                    row.get("ev_after_slippage_25_pp"),
                    row.get("ev_after_slippage_50_pp"),
                    row.get("ev_after_slippage_100_pp"),
                    row.get("ev_after_slippage_250_pp"),
                    row.get("max_size_positive_ev"),
                    row.get("max_size_above_min_edge"),
                    utcnow(),
                ),
            )

    def get_brier_score_data(self, strategies: list[str] | None = None) -> list[dict]:
        """
        Return per-trade Brier score data for closed trades.
        Brier score = (p_hat - actual)^2
        """
        params: list = []
        strategy_filter = ""
        if strategies:
            if self.sqlite_mode:
                strategy_filter = f"AND t.strategy IN ({','.join('?' for _ in strategies)})"
                params = list(strategies)
            else:
                strategy_filter = "AND t.strategy = ANY(%s)"
                params = [strategies]

        query = f"""
            SELECT
                t.strategy,
                t.market_id,
                t.market_title,
                t.outcome,
                t.resolved_outcome,
                t.exit_price          AS actual,
                s.p_hat,
                (s.p_hat - t.exit_price) * (s.p_hat - t.exit_price) AS brier_score,
                t.opened_at,
                t.closed_at
            FROM trades t
            JOIN signals s
              ON  s.market_id  = t.market_id
              AND s.strategy   = t.strategy
              AND s.run_id     = t.run_id_opened
            WHERE t.status          = 'closed'
              AND t.mode            = 'paper'
              AND t.resolved_outcome IN ('YES', 'NO')
              AND s.p_hat IS NOT NULL
              {strategy_filter}
            ORDER BY t.strategy, t.closed_at
        """
        with self._conn() as (conn, cur):
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def get_loss_streaks(self, min_streak: int = 5) -> dict[str, dict]:
        """Return strategies with N+ consecutive recent losses."""
        query = """
            SELECT strategy, pnl_usdc, outcome, resolved_outcome, closed_at
            FROM trades
            WHERE status = 'closed'
              AND mode = 'paper'
              AND resolved_outcome IN ('YES', 'NO')
            ORDER BY strategy, closed_at DESC
        """
        with self._conn() as (conn, cur):
            cur.execute(query)
            rows = cur.fetchall()

        from itertools import groupby
        results = {}
        for strategy, group in groupby(rows, key=lambda r: r["strategy"]):
            streak = 0
            total_lost = 0.0
            last_outcome = ""
            for r in group:
                won = r["resolved_outcome"].upper() == r["outcome"].upper()
                if not won:
                    streak += 1
                    total_lost += abs(float(r["pnl_usdc"]))
                    if streak == 1:
                        last_outcome = r["outcome"]
                else:
                    break
            if streak >= min_streak:
                results[strategy] = {
                    "streak": streak,
                    "total_lost": round(total_lost, 2),
                    "last_outcome": last_outcome,
                }
        return results

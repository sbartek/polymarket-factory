"""SQLite persistence for runs, trades, signals, decisions, logs, and strategy detail rows."""
from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .strategy_meta import ACTIVE_STRATEGIES, strategy_metadata

DB_PATH = Path(__file__).parents[1] / "data" / "factory.sqlite3"
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
PRAGMA journal_mode=WAL;

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
    FOREIGN KEY(run_id_opened) REFERENCES runs(id),
    FOREIGN KEY(run_id_closed) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    level TEXT NOT NULL,
    strategy TEXT,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    market_slug TEXT,
    title TEXT,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS signal_execution_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
CREATE TABLE IF NOT EXISTS market_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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


class FactoryDB:
    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        self._migrate_db()

    def _migrate_db(self):
        migrations = [
            "ALTER TABLE trades ADD COLUMN mode TEXT DEFAULT 'paper'",
            "ALTER TABLE signals ADD COLUMN phase TEXT DEFAULT 'combined'",
            "ALTER TABLE signals ADD COLUMN consumed_by_run_id TEXT",
        ]
        with self._connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(sql)
                    conn.commit()
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e) and "already exists" not in str(e):
                        raise

    def acquire_run_lock(self, name: str, owner_run_id: str, ttl_seconds: int = 7200) -> bool:
        now = utcnow()
        expires = utcnow_plus_seconds(ttl_seconds)
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
            # Database locked by another process — cannot acquire
            try:
                conn.rollback()
            except Exception:
                pass
            return False
        finally:
            conn.close()

    def release_run_lock(self, name: str, owner_run_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM run_locks WHERE name = ? AND owner_run_id = ?", (name, owner_run_id))
            conn.commit()

    def ensure_trades_imported_from_csv(self, csv_path: Path | None = None) -> int:
        csv_path = csv_path or TRADES_CSV
        with self._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            if existing > 0 or not csv_path.exists():
                return 0
            rows = list(csv.DictReader(open(csv_path, newline="")))
            for row in rows:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO trades (
                        id, strategy, market_id, market_title, outcome, amount_usdc, entry_price,
                        shares, opened_at, closes, url, status, exit_price, closed_at,
                        pnl_usdc, resolved_outcome, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("id", ""), row.get("strategy", ""), row.get("market_id", ""), row.get("market_title", ""),
                        row.get("outcome", ""), float(row.get("amount_usdc") or 0), float(row.get("entry_price") or 0),
                        float(row.get("shares") or 0), row.get("opened_at", ""), row.get("closes", ""), row.get("url", ""),
                        row.get("status", "open"), float(row.get("exit_price") or 0), row.get("closed_at", ""),
                        float(row.get("pnl_usdc") or 0), row.get("resolved_outcome", ""), row.get("notes", ""),
                    ),
                )
            conn.commit()
            return len(rows)

    def load_trades(self, mode: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if mode == "paper":
                rows = conn.execute(
                    "SELECT * FROM trades WHERE COALESCE(NULLIF(mode, ''), 'paper') = 'paper' ORDER BY opened_at, id"
                ).fetchall()
            elif mode:
                rows = conn.execute(
                    "SELECT * FROM trades WHERE mode = ? ORDER BY opened_at, id",
                    (mode,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM trades ORDER BY opened_at, id").fetchall()
            return [dict(r) for r in rows]

    def has_open_position(self, market_id: str, strategy: str, mode: str | None = None) -> bool:
        with self._connect() as conn:
            if mode == "paper":
                return conn.execute(
                    "SELECT 1 FROM trades WHERE market_id = ? AND strategy = ? AND status = 'open' AND COALESCE(NULLIF(mode, ''), 'paper') = 'paper' LIMIT 1",
                    (market_id, strategy),
                ).fetchone() is not None
            if mode:
                return conn.execute("SELECT 1 FROM trades WHERE market_id = ? AND strategy = ? AND status = 'open' AND mode = ? LIMIT 1", (market_id, strategy, mode)).fetchone() is not None
            return conn.execute("SELECT 1 FROM trades WHERE market_id = ? AND strategy = ? AND status = 'open' LIMIT 1", (market_id, strategy)).fetchone() is not None

    def insert_trade(self, trade: dict):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (
                    id, strategy, market_id, market_title, outcome, amount_usdc, entry_price,
                    shares, opened_at, closes, url, status, exit_price, closed_at,
                    pnl_usdc, resolved_outcome, notes, run_id_opened, run_id_closed,
                    lifecycle_group, time_window, edge_type, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            conn.commit()

    def close_trade(self, trade_id: str, resolved_outcome: str, run_id_closed: str | None = None) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trades WHERE id = ? AND status = 'open'", (trade_id,)).fetchone()
            if not row:
                return False
            t = dict(row)
            outcome = resolved_outcome.upper()
            shares = float(t["shares"])
            amount = float(t["amount_usdc"])
            # FULL_SET positions always resolve to the full set value; rewards tracked off-chain
            # CANCELLED markets refund — no P&L
            if t.get("outcome") == "FULL_SET" or outcome == "CANCELLED":
                pnl = 0.0
            else:
                pnl = shares * 1.0 - amount if outcome == t["outcome"] else -amount
            conn.execute(
                "UPDATE trades SET status='closed', exit_price=?, closed_at=?, pnl_usdc=?, resolved_outcome=?, run_id_closed=? WHERE id=?",
                (1.0 if outcome == t["outcome"] else 0.0, datetime.now().isoformat(timespec="seconds"), round(pnl, 4), resolved_outcome, run_id_closed, trade_id),
            )
            conn.commit()
            return True

    def backfill_trade_metadata(self) -> int:
        meta = strategy_metadata()
        updated = 0
        with self._connect() as conn:
            rows = conn.execute("SELECT id, strategy, lifecycle_group, time_window, edge_type FROM trades").fetchall()
            for row in rows:
                trade = dict(row)
                strategy = trade.get("strategy")
                strategy_meta = meta.get(strategy, {})
                lifecycle_group = trade.get("lifecycle_group") or ("active" if strategy in ACTIVE_STRATEGIES else "legacy")
                time_window = trade.get("time_window") or strategy_meta.get("time_window")
                edge_type = trade.get("edge_type") or strategy_meta.get("edge_type")

                if trade.get("lifecycle_group") and trade.get("time_window") and trade.get("edge_type"):
                    continue

                conn.execute(
                    "UPDATE trades SET lifecycle_group = ?, time_window = ?, edge_type = ? WHERE id = ?",
                    (lifecycle_group, time_window, edge_type, trade["id"]),
                )
                updated += 1
            conn.commit()
        return updated

    def start_run(self, mode: str, notes: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute("INSERT INTO runs (id, started_at, mode, status, notes) VALUES (?, ?, ?, ?, ?)", (run_id, utcnow(), mode, "running", notes))
            conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str, markets_fetched: int = 0, closed_count: int = 0, new_positions_count: int = 0, notes: str | None = None):
        with self._connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, status=?, markets_fetched=?, closed_count=?, new_positions_count=?, notes=COALESCE(?, notes) WHERE id=?",
                (utcnow(), status, markets_fetched, closed_count, new_positions_count, notes, run_id),
            )
            conn.commit()

    def log_signal(self, run_id: str, strategy: str, signal: dict, time_window: str | None = None, edge_type: str | None = None, decision_status: str | None = None, phase: str = "combined"):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO signals (run_id, strategy, market_id, market_title, outcome, market_price, p_hat, ev_pp, confidence, closes, url, rationale, time_window, edge_type, decision_status, phase, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, strategy, signal.get("market_id", ""), signal.get("market_title", ""), signal.get("outcome", ""), float(signal.get("market_price", 0) or 0), float(signal.get("p_hat", 0) or 0), float(signal.get("ev_pp", 0) or 0), signal.get("confidence", ""), signal.get("closes", ""), signal.get("url", ""), signal.get("rationale", ""), time_window, edge_type, decision_status, phase, utcnow()),
            )
            conn.commit()

    def get_unconsumed_signals(self, max_age_hours: float = 2.0) -> list[dict]:
        """Fetch signals from a scan phase that haven't been consumed yet, deduped by (strategy, market_id, outcome)."""
        cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.* FROM signals s
                INNER JOIN (
                    SELECT strategy, market_id, outcome, MAX(id) AS max_id
                    FROM signals
                    WHERE phase = 'scan'
                      AND consumed_by_run_id IS NULL
                      AND created_at >= ?
                    GROUP BY strategy, market_id, outcome
                ) latest ON s.id = latest.max_id
                ORDER BY s.ev_pp DESC
                """,
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    def has_recent_signal(self, strategy: str, market_id: str, hours: float = 24.0) -> bool:
        """Check if a signal for (strategy, market_id) was generated in the last N hours."""
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM signals WHERE strategy = ? AND market_id = ? AND created_at >= ? LIMIT 1",
                (strategy, market_id, cutoff),
            ).fetchone()
            return row is not None

    def mark_signals_consumed(self, signal_ids: list[int], run_id: str):
        """Mark signals as consumed by an execute-phase run."""
        if not signal_ids:
            return
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in signal_ids)
            conn.execute(
                f"UPDATE signals SET consumed_by_run_id = ? WHERE id IN ({placeholders})",
                [run_id] + signal_ids,
            )
            conn.commit()

    def get_recent_price_moves(self, min_move: float = 0.15, max_hours: float = 6.0) -> list[dict]:
        """Find markets where yes_price moved significantly between the two most recent observations."""
        cutoff = (datetime.now(UTC) - timedelta(hours=max_hours)).isoformat(timespec="seconds")
        query = """
            WITH ranked AS (
                SELECT market_id, market_slug, market_title, yes_price, volume, volume_24hr,
                       close_time, created_at,
                       ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY created_at DESC) as rn
                FROM market_observations
                WHERE yes_price IS NOT NULL AND created_at >= ?
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
              AND ABS(cur.yes_price - prev.yes_price) >= ?
            ORDER BY ABS(cur.yes_price - prev.yes_price) DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query, (cutoff, min_move)).fetchall()
        return [dict(r) for r in rows]

    def log_decision(self, run_id: str, decision_type: str, decision: str, strategy: str | None = None, market_id: str | None = None, reason: str | None = None, details: dict | None = None):
        with self._connect() as conn:
            conn.execute("INSERT INTO decisions (run_id, strategy, market_id, decision_type, decision, reason, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (run_id, strategy, market_id, decision_type, decision, reason, json.dumps(details or {}, ensure_ascii=False), utcnow()))
            conn.commit()

    def log_event(self, run_id: str, level: str, message: str, strategy: str | None = None, payload: dict | None = None):
        with self._connect() as conn:
            conn.execute("INSERT INTO run_logs (run_id, level, strategy, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (run_id, level, strategy, message, json.dumps(payload or {}, ensure_ascii=False), utcnow()))
            conn.commit()

    def log_portfolio_snapshot(self, run_id: str, snapshot: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO portfolio_snapshots (run_id, open_positions, open_cost_usdc, open_mark_value_usdc, unrealized_pnl_usdc, closed_pnl_usdc, net_usdc, marked_positions, stale_positions, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            conn.commit()

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

    def log_market_trades(self, run_id: str, trades_data: list[dict]) -> int:
        """Insert CLOB trades, skipping duplicates by tx_hash. Returns count inserted."""
        if not trades_data:
            return 0
        fetched_at = utcnow()
        inserted = 0
        with self._connect() as conn:
            for t in trades_data:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO market_trades (
                            run_id, condition_id, slug, event_slug, title,
                            outcome, side, price, size, trade_timestamp, tx_hash, fetched_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    if conn.total_changes:
                        inserted += 1
                except Exception as e:
                    print(f"  [db] WARNING: failed to insert market trade: {e}")
                    continue
            conn.commit()
        return inserted

    def get_latest_trade_timestamp(self) -> int:
        """Return the most recent trade_timestamp in market_trades, or 0."""
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(trade_timestamp) AS ts FROM market_trades").fetchone()
            return int(row["ts"]) if row and row["ts"] else 0

    def get_pipeline_health(self) -> list[dict]:
        """Check health of all pipelines. Returns list of dicts with name, last_run, status, age_minutes, overdue."""
        pipelines = [
            {"name": "combined", "mode_pattern": "paper", "expected_interval_min": 150},
            {"name": "scanner", "mode_pattern": "paper_scan", "expected_interval_min": 150},
            {"name": "execute", "mode_pattern": "paper_execute", "expected_interval_min": 150},
            {"name": "observer", "mode_pattern": "observer", "expected_interval_min": 45},
            {"name": "trade_fetcher", "mode_pattern": "trade_fetcher", "expected_interval_min": 45},
        ]
        results = []
        with self._connect() as conn:
            for p in pipelines:
                row = conn.execute(
                    "SELECT finished_at, status FROM runs WHERE mode = ? ORDER BY started_at DESC LIMIT 1",
                    (p["mode_pattern"],),
                ).fetchone()
                if not row or not row["finished_at"]:
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
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as trade_count,
                       COALESCE(SUM(size), 0) as total_size,
                       COALESCE(SUM(size * price), 0) as total_notional
                FROM market_trades
                WHERE slug = ? AND trade_timestamp >= ?
                """,
                (slug, since_ts),
            ).fetchone()
            return dict(row) if row else {"trade_count": 0, "total_size": 0, "total_notional": 0}

    def get_hourly_trade_volume(self, slug: str, hours: int = 168) -> list[dict]:
        """Hourly trade volume bucketed by hour for a market, last N hours (default 7 days)."""
        since_ts = int((datetime.now(UTC) - timedelta(hours=hours)).timestamp())
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT (trade_timestamp / 3600) * 3600 AS hour_ts,
                       COUNT(*) AS trade_count,
                       SUM(size) AS total_size,
                       SUM(size * price) AS total_notional,
                       AVG(price) AS avg_price
                FROM market_trades
                WHERE slug = ? AND trade_timestamp >= ?
                GROUP BY hour_ts
                ORDER BY hour_ts
                """,
                (slug, since_ts),
            ).fetchall()
            return [dict(r) for r in rows]

    def log_market_snapshot_archive(self, run_id: str, events: list[dict], source: str = "fetch_top"):
        payload_json = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO market_snapshot_archives (
                    run_id, source, event_count, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, source, len(events), payload_json, utcnow()),
            )
            conn.commit()

    def get_retention_cleanup_counts(self, retention_days: int = 730) -> dict[str, int]:
        """Count rows eligible for retention cleanup without deleting them."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        result = {}
        with self._connect() as conn:
            for table in RETENTION_CLEANUP_TABLES:
                col = RETENTION_TIMESTAMP_COLS.get(table, "created_at")
                try:
                    count = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {col} < ?",
                        (cutoff,),
                    ).fetchone()[0]
                except Exception as e:
                    print(f"  [db] WARNING: get_retention_cleanup_counts failed for {table}: {e}")
                    count = 0  # table may not exist yet
                result[f"{table}_deleted"] = int(count or 0)
        result["archives_deleted"] = result.get("market_snapshot_archives_deleted", 0)
        result["observations_deleted"] = result.get("market_observations_deleted", 0)
        return result

    def cleanup_old_snapshots(self, retention_days: int = 730) -> dict[str, int]:
        """Delete old rows from all unbounded tables (except trades which are permanent)."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        result = {}
        with self._connect() as conn:
            for table in RETENTION_CLEANUP_TABLES:
                col = RETENTION_TIMESTAMP_COLS.get(table, "created_at")
                try:
                    deleted = conn.execute(
                        f"DELETE FROM {table} WHERE {col} < ?", (cutoff,)
                    ).rowcount
                except Exception as e:
                    print(f"  [db] WARNING: cleanup_old_snapshots failed for {table}: {e}")
                    deleted = 0  # table may not exist yet
                result[f"{table}_deleted"] = deleted
            conn.commit()
        # Backward-compatible keys
        result["archives_deleted"] = result.get("market_snapshot_archives_deleted", 0)
        result["observations_deleted"] = result.get("market_observations_deleted", 0)
        return result

    def get_latest_portfolio_snapshot_before(self, created_at: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM portfolio_snapshots WHERE created_at <= ? ORDER BY created_at DESC LIMIT 1",
                (created_at,),
            ).fetchone()
            return dict(row) if row else None

    def log_spread_arb_basket(self, run_id: str, basket: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO spread_arb_baskets (run_id, event_slug, title, leg_count, total_yes_sum, gap_pp, score, days_to_close, volume, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, basket.get("event_slug"), basket.get("title"), basket.get("leg_count"), basket.get("total_yes_sum"), basket.get("gap_pp"), basket.get("score"), basket.get("days_to_close"), basket.get("volume"), basket.get("decision"), basket.get("reason"), utcnow()),
            )
            conn.commit()

    def log_resolution_hunter_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO resolution_hunter_checks (run_id, market_slug, title, candidate_score, news_count, claude_confidence, claude_outcome, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, row.get("market_slug"), row.get("title"), row.get("candidate_score"), row.get("news_count"), row.get("claude_confidence"), row.get("claude_outcome"), row.get("decision"), row.get("reason"), utcnow()),
            )
            conn.commit()

    def log_stale_market_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO stale_market_checks (run_id, market_slug, title, topic_key, candidate_score, news_count, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, row.get("market_slug"), row.get("title"), row.get("topic_key"), row.get("candidate_score"), row.get("news_count"), row.get("decision"), row.get("reason"), utcnow()),
            )
            conn.commit()

    def log_correlated_pairs_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO correlated_pairs_checks (run_id, slug_a, slug_b, relationship, violation_pp, chosen_slug, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, row.get("slug_a"), row.get("slug_b"), row.get("relationship"), row.get("violation_pp"), row.get("chosen_slug"), row.get("decision"), row.get("reason"), utcnow()),
            )
            conn.commit()

    def log_correlated_laggard_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO correlated_laggard_checks (run_id, leader_slug, laggard_slug, topic_key, leader_price, laggard_price, divergence_pp, volume_ratio, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            conn.commit()

    def log_esport48_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO esport48_checks (run_id, market_slug, title, signal_type, current_price, hours_to_close, volume, liquidity, ev_pp, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            conn.commit()

    def log_celebrity_tabloid_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO celebrity_tabloid_checks (run_id, market_slug, title, subject_names, signal_family, candidate_score, news_hits, corroboration_score, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            conn.commit()

    def log_mutually_exclusive_oversum_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mutually_exclusive_oversum_checks (run_id, market_slug, title, oversum_pp, leg_count, chosen_leg, chosen_yes_price, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            conn.commit()

    def log_polling_vs_market_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO polling_vs_market_checks (run_id, market_slug, title, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    row.get("market_slug"),
                    row.get("title"),
                    row.get("decision"),
                    row.get("reason"),
                    utcnow(),
                ),
            )
            conn.commit()

    def log_signal_execution_check(self, run_id: str, row: dict):
        with self._connect() as conn:
            conn.execute(
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            conn.commit()

    def get_brier_score_data(self, strategies: list[str] | None = None) -> list[dict]:
        """
        Return per-trade Brier score data for closed trades that have a clean YES/NO
        resolved_outcome and a matching signal at open time.

        Only trades where resolved_outcome IN ('YES', 'NO') are included — named-outcome
        markets (sports scores, team names) are skipped because the pnl/exit_price
        normalization is unreliable for those.

        Brier score = (p_hat - actual)^2 where:
          - p_hat  : LLM's probability for the direction we bet (from the opening signal)
          - actual : 1.0 if that direction resolved correctly, 0.0 otherwise (exit_price)
        """
        placeholders = ""
        params: list = []
        if strategies:
            placeholders = f"AND t.strategy IN ({','.join('?' * len(strategies))})"
            params = list(strategies)

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
              {placeholders}
            ORDER BY t.strategy, t.closed_at
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_loss_streaks(self, min_streak: int = 5) -> dict[str, dict]:
        """Return strategies with N+ consecutive recent losses.

        Returns {strategy: {"streak": int, "total_lost": float, "last_outcome": str}}
        for each strategy where the most recent `min_streak` closed trades are all losses.
        """
        query = """
            SELECT strategy, pnl_usdc, outcome, resolved_outcome, closed_at
            FROM trades
            WHERE status = 'closed'
              AND mode = 'paper'
              AND resolved_outcome IN ('YES', 'NO')
            ORDER BY strategy, closed_at DESC
        """
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()

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

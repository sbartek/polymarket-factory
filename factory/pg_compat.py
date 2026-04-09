"""Thin compatibility layer: makes psycopg2 connections behave like sqlite3 for read-only scripts.

Used by scripts that do `conn.execute(sql, params).fetchall()` with `?` placeholders.
Converts `?` to `%s` and wraps results in dict-like rows.
"""
from __future__ import annotations

import os
import re

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# SQLite datetime functions → PostgreSQL equivalents
_SQLITE_DATETIME_RE = re.compile(r"datetime\('now',\s*'(-?\d+)\s+(day|hour|minute)s?'\)")


def _convert_sql(sql: str) -> str:
    """Convert SQLite SQL to PostgreSQL."""
    # ? → %s
    sql = sql.replace("?", "%s")
    # datetime('now', '-30 day') → to_char(NOW() - INTERVAL '30 days', 'YYYY-MM-DD"T"HH24:MI:SS+00:00')
    # Returns TEXT to match the ISO text format stored in columns
    sql = _SQLITE_DATETIME_RE.sub(
        lambda m: (
            f"to_char(NOW() - INTERVAL '{abs(int(m.group(1)))} {m.group(2)}s', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')"
            if int(m.group(1)) < 0
            else f"to_char(NOW() + INTERVAL '{m.group(1)} {m.group(2)}s', 'YYYY-MM-DD\"T\"HH24:MI:SS+00:00')"
        ),
        sql,
    )
    return sql


class CompatCursor:
    """Wraps a psycopg2 DictCursor to accept sqlite3-style ? placeholders."""

    def __init__(self, pg_cursor):
        self._cur = pg_cursor

    def execute(self, sql, params=()):
        self._cur.execute(_convert_sql(sql), params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size)


class CompatConnection:
    """Wraps a psycopg2 connection to behave like sqlite3.Connection with Row factory."""

    def __init__(self, dsn: str | None = None):
        self._conn = psycopg2.connect(dsn or DATABASE_URL)
        self._conn.autocommit = True  # read-only scripts don't need transactions

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(_convert_sql(sql), params)
        return cur

    def cursor(self):
        return CompatCursor(self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor))

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def connect_compat(dsn: str | None = None) -> CompatConnection:
    """Get a sqlite3-compatible connection backed by PostgreSQL."""
    return CompatConnection(dsn)

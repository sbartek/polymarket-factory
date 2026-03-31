"""Unit tests for scripts/backup_db.py — SQLite and CSV backup, and pruning."""
from __future__ import annotations

import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

# Import directly from scripts/ (not a package)
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup_db.py"
_spec = importlib.util.spec_from_file_location("backup_db", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

make_sqlite_backup = _mod.make_sqlite_backup
make_csv_backup = _mod.make_csv_backup
prune_old_backups = _mod.prune_old_backups


@pytest.fixture
def source_db(tmp_path) -> Path:
    db_path = tmp_path / "source.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO test VALUES (42)")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def backup_dir(tmp_path) -> Path:
    d = tmp_path / "backups"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# SQLite backup
# ---------------------------------------------------------------------------

class TestSqliteBackup:
    def test_creates_backup_file(self, source_db, backup_dir):
        dest = make_sqlite_backup(source_db, backup_dir)
        assert dest.exists()

    def test_backup_filename_includes_today(self, source_db, backup_dir):
        dest = make_sqlite_backup(source_db, backup_dir)
        stamp = datetime.now().strftime("%Y-%m-%d")
        assert dest.name == f"factory-{stamp}.sqlite3"

    def test_backup_is_valid_sqlite_with_correct_data(self, source_db, backup_dir):
        dest = make_sqlite_backup(source_db, backup_dir)
        conn = sqlite3.connect(dest)
        row = conn.execute("SELECT id FROM test").fetchone()
        conn.close()
        assert row[0] == 42

    def test_no_leftover_tmp_file(self, source_db, backup_dir):
        make_sqlite_backup(source_db, backup_dir)
        tmp_files = list(backup_dir.glob(".*.tmp"))
        assert tmp_files == []

    def test_raises_if_source_db_missing(self, backup_dir):
        with pytest.raises(FileNotFoundError):
            make_sqlite_backup(backup_dir / "nonexistent.sqlite3", backup_dir)

    def test_creates_backup_dir_if_absent(self, source_db, tmp_path):
        absent_dir = tmp_path / "new_backups"
        assert not absent_dir.exists()
        dest = make_sqlite_backup(source_db, absent_dir)
        assert dest.exists()


# ---------------------------------------------------------------------------
# CSV backup
# ---------------------------------------------------------------------------

class TestCsvBackup:
    def test_copies_csv_to_backup_dir(self, tmp_path, backup_dir):
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text("id,strategy\nt1,ev_news\n")
        dest = make_csv_backup(csv_path, backup_dir)
        assert dest is not None
        assert dest.exists()

    def test_backup_csv_filename_includes_today(self, tmp_path, backup_dir):
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text("id\n")
        dest = make_csv_backup(csv_path, backup_dir)
        stamp = datetime.now().strftime("%Y-%m-%d")
        assert dest.name == f"trades-{stamp}.csv"

    def test_backup_csv_content_matches_source(self, tmp_path, backup_dir):
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text("id,strategy\nt1,ev_news\n")
        dest = make_csv_backup(csv_path, backup_dir)
        assert dest.read_text() == "id,strategy\nt1,ev_news\n"

    def test_no_leftover_tmp_file(self, tmp_path, backup_dir):
        csv_path = tmp_path / "trades.csv"
        csv_path.write_text("id\n")
        make_csv_backup(csv_path, backup_dir)
        tmp_files = list(backup_dir.glob(".*.tmp"))
        assert tmp_files == []

    def test_returns_none_if_csv_missing(self, tmp_path, backup_dir):
        result = make_csv_backup(tmp_path / "nope.csv", backup_dir)
        assert result is None


# ---------------------------------------------------------------------------
# Prune old backups
# ---------------------------------------------------------------------------

class TestPruneOldBackups:
    def _touch(self, backup_dir: Path, *names: str) -> None:
        for name in names:
            (backup_dir / name).write_text("")

    def test_removes_oldest_sqlite_backups(self, backup_dir):
        self._touch(
            backup_dir,
            "factory-2026-01-01.sqlite3",
            "factory-2026-01-02.sqlite3",
            "factory-2026-01-03.sqlite3",
        )
        prune_old_backups(backup_dir, keep=2)
        remaining = sorted(backup_dir.glob("factory-*.sqlite3"))
        assert len(remaining) == 2
        assert not (backup_dir / "factory-2026-01-01.sqlite3").exists()

    def test_keeps_newest_sqlite_backups(self, backup_dir):
        self._touch(
            backup_dir,
            "factory-2026-01-01.sqlite3",
            "factory-2026-01-02.sqlite3",
            "factory-2026-01-03.sqlite3",
        )
        prune_old_backups(backup_dir, keep=2)
        assert (backup_dir / "factory-2026-01-02.sqlite3").exists()
        assert (backup_dir / "factory-2026-01-03.sqlite3").exists()

    def test_removes_oldest_csv_backups(self, backup_dir):
        self._touch(
            backup_dir,
            "trades-2026-01-01.csv",
            "trades-2026-01-02.csv",
            "trades-2026-01-03.csv",
        )
        prune_old_backups(backup_dir, keep=1)
        remaining = list(backup_dir.glob("trades-*.csv"))
        assert len(remaining) == 1
        assert (backup_dir / "trades-2026-01-03.csv").exists()

    def test_no_prune_when_within_limit(self, backup_dir):
        self._touch(backup_dir, "factory-2026-01-01.sqlite3", "factory-2026-01-02.sqlite3")
        removed = prune_old_backups(backup_dir, keep=14)
        assert removed == []

    def test_returns_list_of_removed_paths(self, backup_dir):
        self._touch(
            backup_dir,
            "factory-2026-01-01.sqlite3",
            "factory-2026-01-02.sqlite3",
            "factory-2026-01-03.sqlite3",
        )
        removed = prune_old_backups(backup_dir, keep=1)
        assert len(removed) == 2
        assert all(isinstance(p, Path) for p in removed)

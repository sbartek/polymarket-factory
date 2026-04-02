from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_dashboard_data.py"
SPEC = importlib.util.spec_from_file_location("export_dashboard_data", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
export_dashboard_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_dashboard_data)


def test_connect_db_initializes_signal_execution_checks_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "factory.sqlite3"
    monkeypatch.setattr(export_dashboard_data, "DB_PATH", db_path)

    conn = export_dashboard_data.connect_db()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'signal_execution_checks'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None

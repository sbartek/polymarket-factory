from __future__ import annotations

import importlib.util
from pathlib import Path

from factory.db import FactoryDB


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


def test_fetch_execution_checks_returns_recent_rows(tmp_path):
    db = FactoryDB(path=tmp_path / "factory.sqlite3")
    run_id = db.start_run("dry_run")
    db.finish_run(run_id, "success", markets_fetched=10)
    db.log_signal_execution_check(run_id, {
        "strategy": "esport48",
        "market_id": "m1",
        "market_title": "Example market",
        "outcome": "YES",
        "quote_price": 0.21,
        "best_bid": 0.19,
        "best_ask": 0.22,
        "fill_price_10": 0.2205,
        "fill_price_25": 0.225,
        "fill_price_50": 0.23,
        "fill_price_100": 0.24,
        "fill_price_250": 0.3,
        "slippage_10_pp": 1.05,
        "slippage_25_pp": 1.5,
        "slippage_50_pp": 2.0,
        "slippage_100_pp": 3.0,
        "slippage_250_pp": 9.0,
        "ev_after_slippage_10_pp": 12.0,
        "ev_after_slippage_25_pp": 11.5,
        "ev_after_slippage_50_pp": 11.0,
        "ev_after_slippage_100_pp": 10.0,
        "ev_after_slippage_250_pp": 4.0,
        "max_size_positive_ev": 100.0,
        "max_size_above_min_edge": 50.0,
        "source_confidence": "medium",
    })

    conn = db._connect()
    try:
        rows = export_dashboard_data.fetch_execution_checks(conn, limit=10)
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["strategy"] == "esport48"
    assert rows[0]["market_title"] == "Example market"
    assert rows[0]["fill_price_50"] == 0.23
    assert rows[0]["ev_after_slippage_50_pp"] == 11.0

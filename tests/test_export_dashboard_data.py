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


def test_load_benchmarks_reads_available_scopes(tmp_path, monkeypatch):
    benchmark_dir = tmp_path / "benchmark-data"
    benchmark_dir.mkdir()
    (benchmark_dir / "replay-benchmark-alert-only.json").write_text(
        '{"generated_at":"2026-04-03T17:51:11","scope":"alert-only","strategy_count":1,"signal_count":2,"strategies":[{"strategy":"esport48","benchmark_score":0.73}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(export_dashboard_data, "BENCHMARK_DIR", benchmark_dir)

    payload = export_dashboard_data.load_benchmarks()

    assert payload["available_scopes"] == ["alert-only"]
    assert payload["scopes"]["alert-only"]["strategies"][0]["strategy"] == "esport48"


def test_fetch_overview_includes_benchmark_coverage_counts(tmp_path, monkeypatch):
    db_path = tmp_path / "factory.sqlite3"
    db = FactoryDB(path=db_path)
    run_id = db.start_run("paper")
    db.finish_run(run_id, "success", markets_fetched=10)
    monkeypatch.setattr(export_dashboard_data, "DB_PATH", db_path)

    conn = export_dashboard_data.connect_db()
    try:
        overview = export_dashboard_data.fetch_overview(
            conn,
            experiments=[],
            warnings=[],
            benchmarks={
                "scopes": {
                    "alert-only": {
                        "strategy_count": 2,
                        "signal_count": 10,
                        "strategies": [
                            {
                                "strategy": "esport48",
                                "benchmark_score": 0.71,
                                "observed_signals": 6,
                                "labeled_signals": 4,
                                "no_forward_observation_signals": 2,
                            },
                            {
                                "strategy": "correlated_laggard",
                                "benchmark_score": 0.68,
                                "observed_signals": 1,
                                "labeled_signals": 0,
                                "no_forward_observation_signals": 3,
                            },
                        ],
                    }
                }
            },
        )
    finally:
        conn.close()

    assert overview["benchmark_observed_signal_count_alert_only"] == 7
    assert overview["benchmark_labeled_signal_count_alert_only"] == 4
    assert overview["benchmark_missing_forward_signal_count_alert_only"] == 5


def test_load_generated_registry_includes_archived_reason_and_benchmark(tmp_path, monkeypatch):
    generated_dir = tmp_path / "factory" / "strategies" / "generated"
    archive_dir = generated_dir / "archive"
    proposals_dir = tmp_path / "improvement" / "proposals"
    generated_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)
    proposals_dir.mkdir(parents=True)

    (archive_dir / "auto_20260403_001_bad_edge__archived_20260403_190000.py").write_text(
        'class X:\n    name = "bad_edge"\n',
        encoding="utf-8",
    )
    (proposals_dir / "PR-20260403-001-bad_edge.md").write_text(
        "- **status:** archived\n\n## Benchmark gate note\n\nArchived by benchmark gate: benchmark_score 0.410 below 0.60\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(export_dashboard_data, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(export_dashboard_data, "GENERATED_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(export_dashboard_data, "PROPOSALS_DIR", proposals_dir)
    monkeypatch.setattr(export_dashboard_data, "PROJECT_ROOT", tmp_path)

    rows = export_dashboard_data.load_generated_registry({
        "scopes": {
            "generated": {
                "strategies": [
                    {"strategy": "bad_edge", "benchmark_score": 0.41, "signals": 8, "labeled_signals": 4}
                ]
            }
        }
    })

    assert rows["bad_edge"]["generated_lifecycle"] == "archived"
    assert "benchmark_score 0.410 below 0.60" in rows["bad_edge"]["archive_reason"]
    assert rows["bad_edge"]["generated_benchmark_score"] == 0.41


def test_load_generated_registry_includes_coverage_fields(tmp_path, monkeypatch):
    generated_dir = tmp_path / "factory" / "strategies" / "generated"
    generated_dir.mkdir(parents=True)
    (generated_dir / "auto_20260403_001_good_edge.py").write_text(
        'class X:\n    name = "good_edge"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(export_dashboard_data, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(export_dashboard_data, "GENERATED_ARCHIVE_DIR", generated_dir / "archive")
    monkeypatch.setattr(export_dashboard_data, "PROPOSALS_DIR", tmp_path / "improvement" / "proposals")
    monkeypatch.setattr(export_dashboard_data, "PROJECT_ROOT", tmp_path)

    rows = export_dashboard_data.load_generated_registry({
        "scopes": {
            "generated": {
                "strategies": [
                    {
                        "strategy": "good_edge",
                        "benchmark_score": 0.73,
                        "signals": 9,
                        "observed_signals": 5,
                        "labeled_signals": 3,
                        "no_forward_observation_signals": 4,
                        "flat_observation_signals": 1,
                    }
                ]
            }
        }
    })

    assert rows["good_edge"]["generated_benchmark_observed"] == 5
    assert rows["good_edge"]["generated_benchmark_missing_forward"] == 4
    assert rows["good_edge"]["generated_benchmark_flat_observations"] == 1


def test_fetch_storage_reports_sizes_and_recent_archives(tmp_path, monkeypatch):
    db_path = tmp_path / "factory.sqlite3"
    benchmark_dir = tmp_path / "benchmark-data"
    output_dir = tmp_path / "dashboard-data"
    project_root = tmp_path / "project"
    benchmark_dir.mkdir()
    output_dir.mkdir()
    project_root.mkdir()
    (project_root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (benchmark_dir / "sample.json").write_text('{"ok":true}\n', encoding="utf-8")
    (output_dir / "sample.json").write_text('{"ok":true}\n', encoding="utf-8")

    db = FactoryDB(path=db_path)
    run_id = db.start_run("paper")
    db.log_market_snapshot_archive(run_id, [{"slug": "event-a"}])
    db.log_market_observations(run_id, [{"market_id": "event-a", "market_title": "Event A"}])

    monkeypatch.setattr(export_dashboard_data, "DB_PATH", db_path)
    monkeypatch.setattr(export_dashboard_data, "BENCHMARK_DIR", benchmark_dir)
    monkeypatch.setattr(export_dashboard_data, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(export_dashboard_data, "PROJECT_ROOT", project_root)

    conn = db._connect()
    try:
        storage = export_dashboard_data.fetch_storage(conn)
    finally:
        conn.close()

    assert storage["database_bytes"] > 0
    assert storage["benchmark_data_bytes"] > 0
    assert storage["dashboard_data_bytes"] > 0
    assert storage["project_storage_bytes"] > 0
    assert storage["raw_snapshot_archive_runs"] == 1
    assert storage["market_observation_rows"] == 1
    assert storage["raw_snapshot_retention_days"] == 730
    assert storage["disk_total_bytes"] > 0
    assert storage["disk_free_bytes"] > 0
    assert 0 <= storage["disk_free_pct"] <= 1.0
    assert isinstance(storage["disk_free_alert"], bool)
    assert len(storage["recent_snapshot_archives"]) == 1

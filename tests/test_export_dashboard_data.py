from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_dashboard_data.py"
SPEC = importlib.util.spec_from_file_location("export_dashboard_data", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
export_dashboard_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_dashboard_data)


def _sqlite_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_connect_db_opens_sqlite_when_database_url_absent(tmp_path, monkeypatch):
    db_path = tmp_path / "factory.sqlite3"
    monkeypatch.setattr(export_dashboard_data, "DB_PATH", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    conn = export_dashboard_data.connect_db()
    try:
        row = conn.execute("SELECT 1 AS ok").fetchone()
    finally:
        conn.close()

    assert row["ok"] == 1


def test_fetch_execution_checks_returns_recent_rows(tmp_path):
    conn = _sqlite_db(tmp_path / "factory.sqlite3")
    try:
        conn.execute(
            """
            CREATE TABLE signal_execution_checks (
                run_id TEXT,
                strategy TEXT,
                market_id TEXT,
                market_title TEXT,
                outcome TEXT,
                quote_price REAL,
                best_bid REAL,
                best_ask REAL,
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
                source_confidence TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO signal_execution_checks (
                run_id, strategy, market_id, market_title, outcome, quote_price, best_bid, best_ask,
                fill_price_10, fill_price_25, fill_price_50, fill_price_100, fill_price_250,
                slippage_10_pp, slippage_25_pp, slippage_50_pp, slippage_100_pp, slippage_250_pp,
                ev_after_slippage_10_pp, ev_after_slippage_25_pp, ev_after_slippage_50_pp,
                ev_after_slippage_100_pp, ev_after_slippage_250_pp, max_size_positive_ev,
                max_size_above_min_edge, source_confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "run-1", "esport48", "m1", "Example market", "YES", 0.21, 0.19, 0.22,
                0.2205, 0.225, 0.23, 0.24, 0.3,
                1.05, 1.5, 2.0, 3.0, 9.0,
                12.0, 11.5, 11.0, 10.0, 4.0, 100.0, 50.0, "medium",
            ),
        )
        conn.commit()
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
    monkeypatch.setattr(export_dashboard_data, "DB_PATH", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    conn = _sqlite_db(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                started_at TEXT,
                finished_at TEXT,
                mode TEXT,
                status TEXT,
                markets_fetched INTEGER,
                closed_count INTEGER,
                new_positions_count INTEGER,
                notes TEXT
            )
            """
        )
        conn.execute("CREATE TABLE trades (strategy TEXT, status TEXT, amount_usdc REAL)")
        conn.execute(
            """
            CREATE TABLE signal_execution_checks (
                strategy TEXT,
                ev_after_slippage_50_pp REAL,
                max_size_positive_ev REAL,
                source_confidence TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "2026-04-10T09:30:00+00:00", "2026-04-10T09:31:00+00:00", "paper", "success", 10, 0, 0, None),
        )
        conn.execute(
            "INSERT INTO signal_execution_checks VALUES (?, ?, ?, ?, datetime('now'))",
            ("esport48", 11.0, 50.0, "medium"),
        )
        conn.commit()
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


def test_load_strategy_factory_status_reads_latest_run(tmp_path, monkeypatch):
    run_dir = tmp_path / "strategy-factory-runs"
    run_dir.mkdir(parents=True)
    (run_dir / "latest.json").write_text(
        """
        {
          "started_at": "2026-04-10T07:30:00+00:00",
          "finished_at": "2026-04-10T07:31:00+00:00",
          "status": "degraded",
          "eval_source": "cache",
          "generated_count": 2,
          "archived_count": 1,
          "degraded": true,
          "push_ok": true,
          "heartbeat_ok": true,
          "preflight_ok": true,
          "error": null
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(export_dashboard_data, "STRATEGY_FACTORY_RUNS_DIR", run_dir)

    payload = export_dashboard_data.load_strategy_factory_status()

    assert payload["status"] == "degraded"
    assert payload["status_normalized"] == "warning"
    assert payload["eval_source"] == "cache"
    assert payload["generated_count"] == 2


def test_load_strategy_factory_history_reads_recent_runs(tmp_path, monkeypatch):
    run_dir = tmp_path / "strategy-factory-runs"
    run_dir.mkdir(parents=True)
    for idx, status in enumerate(["ok", "degraded"], start=1):
        (run_dir / f"strategy-factory-20260410T0{idx}0000Z.json").write_text(
            f'{{"started_at":"2026-04-10T0{idx}:00:00+00:00","finished_at":"2026-04-10T0{idx}:01:00+00:00","status":"{status}","eval_source":"remote","generated_count":{idx},"archived_count":0}}',
            encoding="utf-8",
        )
    monkeypatch.setattr(export_dashboard_data, "STRATEGY_FACTORY_RUNS_DIR", run_dir)

    rows = export_dashboard_data.load_strategy_factory_history(limit=5)

    assert len(rows) == 2
    assert rows[0]["status"] == "degraded"
    assert rows[1]["status"] == "ok"


def test_fetch_overview_includes_strategy_factory_alert(tmp_path, monkeypatch):
    class _Row(dict):
        def __getitem__(self, key):
            return dict.__getitem__(self, key)

    class _Cursor:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

        def fetchall(self):
            return []

    class _Conn:
        def execute(self, sql, params=()):
            if "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1" in sql:
                return _Cursor(_Row({
                    "status": "success",
                    "started_at": "2026-04-10T09:30:00+00:00",
                    "finished_at": "2026-04-10T09:31:00+00:00",
                }))
            return _Cursor(None)

    monkeypatch.setattr(export_dashboard_data, "scalar", lambda *args, **kwargs: 0)
    monkeypatch.setattr(export_dashboard_data, "fetch_execution_summary", lambda conn: {
        "checks_30d": 1,
        "strategies_with_checks_30d": 1,
        "avg_ev_after_slippage_50_pp_30d": 1.0,
        "avg_max_size_positive_ev_30d": 10.0,
        "source_confidence_counts_30d": {"medium": 1},
    })

    overview = export_dashboard_data.fetch_overview(
        _Conn(),
        experiments=[],
        warnings=[],
        benchmarks={},
        storage=None,
        strategy_factory={
            "status": "failed",
            "degraded": False,
            "eval_source": "remote",
            "error": "git push failed",
        },
    )

    assert overview["strategy_factory"]["status"] == "failed"
    assert any("Strategy factory failed" in row["message"] for row in overview["alerts"])


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

    monkeypatch.setattr(export_dashboard_data, "DB_PATH", db_path)
    monkeypatch.setattr(export_dashboard_data, "BENCHMARK_DIR", benchmark_dir)
    monkeypatch.setattr(export_dashboard_data, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(export_dashboard_data, "PROJECT_ROOT", project_root)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    conn = _sqlite_db(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE market_snapshot_archives (
                run_id TEXT PRIMARY KEY,
                source TEXT,
                event_count INTEGER,
                payload_json TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE market_observations (
                id INTEGER PRIMARY KEY,
                run_id TEXT,
                market_id TEXT,
                market_title TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO market_snapshot_archives VALUES (?, ?, ?, ?, datetime('now'))",
            ("run-1", "gamma", 1, '[{\"slug\":\"event-a\"}]'),
        )
        conn.execute(
            "INSERT INTO market_observations (run_id, market_id, market_title, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("run-1", "event-a", "Event A"),
        )
        conn.commit()
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

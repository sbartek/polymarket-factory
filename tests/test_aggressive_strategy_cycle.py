from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "aggressive_strategy_cycle.py"
SPEC = importlib.util.spec_from_file_location("aggressive_strategy_cycle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
aggressive_strategy_cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aggressive_strategy_cycle)


def test_apply_generated_retention_gate_archives_old_unbenchmarked_module(tmp_path, monkeypatch):
    generated_dir = tmp_path / "generated"
    archive_dir = generated_dir / "archive"
    proposals_dir = tmp_path / "proposals"
    benchmark_dir = tmp_path / "benchmark-data"
    generated_dir.mkdir(parents=True)
    proposals_dir.mkdir(parents=True)
    benchmark_dir.mkdir(parents=True)

    module = generated_dir / "auto_20260401_001_old_strategy.py"
    module.write_text('class X:\n    name = "old_strategy"\n', encoding="utf-8")
    proposal = proposals_dir / "PR-20260401-001-old_strategy.md"
    proposal.write_text("- **status:** pending_benchmark_review\n", encoding="utf-8")

    old_ts = 1_743_465_600  # 2025-04-01-ish, safely old relative to test runtime
    module.touch()
    import os
    os.utime(module, (old_ts, old_ts))

    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "PROPOSALS_DIR", proposals_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "BENCHMARK_DIR", benchmark_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_RETENTION_GRACE_DAYS", 0)

    archived = aggressive_strategy_cycle.apply_generated_retention_gate()

    assert len(archived) == 1
    assert archived[0]["strategy_name"] == "old_strategy"
    assert list(archive_dir.glob("auto_20260401_001_old_strategy__archived_*.py"))
    assert "archived" in proposal.read_text(encoding="utf-8")


def test_apply_generated_retention_gate_archives_low_scoring_benchmarked_module(tmp_path, monkeypatch):
    generated_dir = tmp_path / "generated"
    archive_dir = generated_dir / "archive"
    proposals_dir = tmp_path / "proposals"
    benchmark_dir = tmp_path / "benchmark-data"
    generated_dir.mkdir(parents=True)
    proposals_dir.mkdir(parents=True)
    benchmark_dir.mkdir(parents=True)

    module = generated_dir / "auto_20260403_001_bad_edge.py"
    module.write_text('class X:\n    name = "bad_edge"\n', encoding="utf-8")
    (benchmark_dir / "replay-benchmark-generated.json").write_text(json.dumps({
        "strategies": [{
            "strategy": "bad_edge",
            "signals": 8,
            "observed_signals": 4,
            "labeled_signals": 4,
            "observation_coverage": 0.50,
            "benchmark_score": 0.41,
        }]
    }), encoding="utf-8")

    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "PROPOSALS_DIR", proposals_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "BENCHMARK_DIR", benchmark_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_RETENTION_GRACE_DAYS", 30)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_SIGNALS_FOR_GATE", 5)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_LABELED_FOR_GATE", 3)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_OBSERVED_SIGNALS_FOR_GATE", 3)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_OBSERVATION_COVERAGE", 0.30)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_BENCHMARK_SCORE", 0.60)

    archived = aggressive_strategy_cycle.apply_generated_retention_gate()

    assert len(archived) == 1
    assert archived[0]["strategy_name"] == "bad_edge"


def test_apply_generated_retention_gate_keeps_low_scoring_module_pending_when_coverage_is_thin(tmp_path, monkeypatch):
    generated_dir = tmp_path / "generated"
    archive_dir = generated_dir / "archive"
    proposals_dir = tmp_path / "proposals"
    benchmark_dir = tmp_path / "benchmark-data"
    generated_dir.mkdir(parents=True)
    proposals_dir.mkdir(parents=True)
    benchmark_dir.mkdir(parents=True)

    module = generated_dir / "auto_20260403_001_thin_evidence.py"
    module.write_text('class X:\n    name = "thin_evidence"\n', encoding="utf-8")
    proposal = proposals_dir / "PR-20260403-001-thin_evidence.md"
    proposal.write_text("- **status:** pending_benchmark_review\n", encoding="utf-8")
    (benchmark_dir / "replay-benchmark-generated.json").write_text(json.dumps({
        "strategies": [{
            "strategy": "thin_evidence",
            "signals": 8,
            "observed_signals": 1,
            "labeled_signals": 1,
            "observation_coverage": 0.12,
            "benchmark_score": 0.20,
        }]
    }), encoding="utf-8")

    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "PROPOSALS_DIR", proposals_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "BENCHMARK_DIR", benchmark_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_RETENTION_GRACE_DAYS", 30)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_SIGNALS_FOR_GATE", 5)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_LABELED_FOR_GATE", 3)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_OBSERVED_SIGNALS_FOR_GATE", 3)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_OBSERVATION_COVERAGE", 0.30)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MIN_BENCHMARK_SCORE", 0.60)

    archived = aggressive_strategy_cycle.apply_generated_retention_gate()

    assert archived == []
    assert module.exists()
    text = proposal.read_text(encoding="utf-8")
    assert "pending_benchmark_review" in text
    assert "Benchmark evidence still too thin for archive decision" in text

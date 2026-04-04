"""Tests for generated strategy hard TTL expiry."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import scripts.aggressive_strategy_cycle as aggressive_strategy_cycle


def test_hard_ttl_archives_old_insufficient_evidence_module(tmp_path, monkeypatch):
    """A strategy with a benchmark but insufficient evidence should be archived after GENERATED_MAX_TTL_DAYS."""
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    archive_dir = gen_dir / "archive"

    module_file = gen_dir / "old_strat.py"
    module_file.write_text("# strategy\nname = 'old_strat'\n")

    # Set mtime to 20 days ago
    old_time = (datetime.now() - timedelta(days=20)).timestamp()
    import os
    os.utime(module_file, (old_time, old_time))

    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_DIR", gen_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MAX_TTL_DAYS", 14)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_RETENTION_GRACE_DAYS", 3)

    # Return a benchmark with insufficient evidence
    monkeypatch.setattr(
        aggressive_strategy_cycle,
        "benchmark_lookup",
        lambda scope: {
            "old_strat": {
                "benchmark_score": 0.3,
                "signals": 2,           # < GENERATED_MIN_SIGNALS_FOR_GATE (5)
                "labeled_signals": 1,
                "observed_signals": 1,
                "observation_coverage": 0.1,
            }
        },
    )

    monkeypatch.setattr(
        aggressive_strategy_cycle,
        "generated_module_rows",
        lambda: [
            {
                "path": module_file,
                "module_name": "old_strat",
                "strategy_name": "old_strat",
                "mtime": datetime.now() - timedelta(days=20),
            }
        ],
    )

    monkeypatch.setattr(aggressive_strategy_cycle, "proposal_paths_for_strategy", lambda name: [])
    monkeypatch.setattr(aggressive_strategy_cycle, "rewrite_proposal_status", lambda paths, status, note: None)

    archived = aggressive_strategy_cycle.apply_generated_retention_gate()

    assert len(archived) == 1
    assert "hard TTL" in archived[0]["reason"]


def test_ttl_does_not_archive_young_insufficient_evidence_module(tmp_path, monkeypatch):
    """A young strategy with insufficient evidence should NOT be archived — only marked pending."""
    gen_dir = tmp_path / "generated"
    gen_dir.mkdir()
    archive_dir = gen_dir / "archive"

    module_file = gen_dir / "young_strat.py"
    module_file.write_text("# strategy\nname = 'young_strat'\n")

    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_DIR", gen_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_MAX_TTL_DAYS", 14)
    monkeypatch.setattr(aggressive_strategy_cycle, "GENERATED_RETENTION_GRACE_DAYS", 30)

    monkeypatch.setattr(
        aggressive_strategy_cycle,
        "benchmark_lookup",
        lambda scope: {
            "young_strat": {
                "benchmark_score": 0.3,
                "signals": 2,
                "labeled_signals": 1,
                "observed_signals": 1,
                "observation_coverage": 0.1,
            }
        },
    )

    pending_calls = []
    monkeypatch.setattr(
        aggressive_strategy_cycle,
        "mark_generated_pending_review",
        lambda row, note: pending_calls.append(row["strategy_name"]),
    )

    monkeypatch.setattr(
        aggressive_strategy_cycle,
        "generated_module_rows",
        lambda: [
            {
                "path": module_file,
                "module_name": "young_strat",
                "strategy_name": "young_strat",
                "mtime": datetime.now() - timedelta(days=5),  # < 14 days
            }
        ],
    )

    archived = aggressive_strategy_cycle.apply_generated_retention_gate()

    assert len(archived) == 0
    assert "young_strat" in pending_calls

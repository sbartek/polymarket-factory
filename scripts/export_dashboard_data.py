#!/usr/bin/env python3
"""Export reduced dashboard snapshot data for the PPLayouts external dashboard."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.pg_compat import connect_compat
from factory.strategy_meta import strategy_metadata, ACTIVE_STRATEGIES as _CANONICAL_ACTIVE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "factory.sqlite3"
OUTPUT_DIR = PROJECT_ROOT / "dashboard-data"
BENCHMARK_DIR = PROJECT_ROOT / "benchmark-data"
IMPROVEMENT_DIR = PROJECT_ROOT / "improvement"
CHANGES_DIR = IMPROVEMENT_DIR / "changes"
EXPERIMENTS_DIR = IMPROVEMENT_DIR / "experiments"
REVIEWS_DIR = IMPROVEMENT_DIR / "reviews"
PROPOSALS_DIR = IMPROVEMENT_DIR / "proposals"
GENERATED_DIR = PROJECT_ROOT / "factory" / "strategies" / "generated"
GENERATED_ARCHIVE_DIR = GENERATED_DIR / "archive"
STRATEGY_FACTORY_RUNS_DIR = PROJECT_ROOT / "data" / "strategy-factory-runs"

ACTIVE_STRATEGIES = _CANONICAL_ACTIVE
TIME_WINDOWS = ["super_short", "intraday", "short", "medium", "long", "unknown"]
RAW_SNAPSHOT_RETENTION_DAYS = 365 * 2
DISK_FREE_ALERT_THRESHOLD = 0.20  # alert when less than 20% of disk is free
PROJECT_STORAGE_EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def load_dotenv() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def seconds_between(start: str | None, end: str | None) -> int | None:
    s = parse_iso(start)
    e = parse_iso(end)
    if not s or not e:
        return None
    return max(0, int((e - s).total_seconds()))


def normalize_status(raw: str | None) -> str:
    if not raw:
        return "unknown"
    raw = raw.strip().lower()
    if raw in {"ok", "success", "done", "completed"}:
        return "ok"
    if raw in {"warning", "warn", "partial", "degraded"}:
        return "warning"
    if raw in {"error", "failed", "fail"}:
        return "error"
    return "unknown"


def load_strategy_factory_status() -> dict | None:
    path = STRATEGY_FACTORY_RUNS_DIR / "latest.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw_status = (payload.get("status") or "unknown").strip().lower()
    return {
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "status": raw_status,
        "status_normalized": normalize_status(raw_status),
        "eval_source": payload.get("eval_source"),
        "generated_count": payload.get("generated_count"),
        "archived_count": payload.get("archived_count"),
        "degraded": bool(payload.get("degraded")),
        "push_ok": bool(payload.get("push_ok")),
        "heartbeat_ok": bool(payload.get("heartbeat_ok")),
        "preflight_ok": bool(payload.get("preflight_ok")),
        "error": payload.get("error"),
    }


def load_strategy_factory_history(limit: int = 5) -> list[dict]:
    if not STRATEGY_FACTORY_RUNS_DIR.exists():
        return []
    rows: list[dict] = []
    for path in sorted(STRATEGY_FACTORY_RUNS_DIR.glob("strategy-factory-*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append({
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "status": payload.get("status"),
            "status_normalized": normalize_status(payload.get("status")),
            "eval_source": payload.get("eval_source"),
            "generated_count": payload.get("generated_count"),
            "archived_count": payload.get("archived_count"),
            "degraded": bool(payload.get("degraded")),
            "error": payload.get("error"),
        })
        if len(rows) >= limit:
            break
    return rows


PAUSED_STRATEGIES = {"fade_certainty", "weather_edge"}


def strategy_status(name: str, open_count: int = 0) -> str:
    if name in ACTIVE_STRATEGIES:
        return "active"
    if name in PAUSED_STRATEGIES:
        return "paused"
    if open_count > 0:
        return "legacy"
    return "legacy"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_field(text: str, field: str) -> str:
    m = re.search(rf"^\s*- \*\*{re.escape(field)}:\*\*[ \t]*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def extract_section(text: str, heading: str) -> str:
    m = re.search(rf"^\s*## {re.escape(heading)}\s*\n\n(.+?)(\n\s*## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def slugify(text: str) -> str:
    return "_".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())[:48] or "generated_strategy"


def load_changes() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(CHANGES_DIR.glob("CR-*.md")):
        text = read_text(path)
        change_id = extract_field(text, "change_id") or path.stem
        rows[change_id] = {
            "change_id": change_id,
            "date": extract_field(text, "date"),
            "component": extract_field(text, "component"),
            "owner": extract_field(text, "owner"),
            "status": extract_field(text, "status"),
            "summary": extract_section(text, "Summary"),
            "hypothesis": extract_section(text, "Hypothesis"),
            "path": str(path.relative_to(PROJECT_ROOT)),
        }
    return rows


def load_reviews() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in sorted(REVIEWS_DIR.glob("RV-*.md")):
        text = read_text(path)
        review_id = extract_field(text, "review_id") or path.stem
        raw_change_ids = extract_field(text, "related_change_ids")
        raw_experiment_ids = extract_field(text, "related_experiment_ids")
        rows[review_id] = {
            "review_id": review_id,
            "date": extract_field(text, "date"),
            "recommendation": extract_section(text, "Recommendation"),
            "related_change_ids": [s.strip() for s in raw_change_ids.split(",") if s.strip()],
            "related_experiment_ids": [s.strip() for s in raw_experiment_ids.split(",") if s.strip()],
            "path": str(path.relative_to(PROJECT_ROOT)),
        }
    return rows


def load_experiments(changes: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(EXPERIMENTS_DIR.glob("EX-*.md")):
        text = read_text(path)
        experiment_id = extract_field(text, "experiment_id") or path.stem
        related_change_id = extract_field(text, "related_change_id")
        status = normalize_experiment_status((extract_field(text, "status") or "unknown").strip().lower())
        title = extract_field(text, "component") or experiment_id
        scope_type, scope_label, strategy = infer_experiment_scope(title, text, related_change_id, changes)
        rows.append({
            "experiment_id": experiment_id,
            "title": title,
            "scope_type": scope_type,
            "scope_label": scope_label,
            "strategy": strategy,
            "status": status,
            "hypothesis": extract_section(text, "Hypothesis"),
            "linked_changes": [related_change_id] if related_change_id else [],
            "linked_reviews": [],
            "review_due": infer_review_due(text),
            "last_updated": extract_field(text, "date") or None,
            "summary": summarize_experiment(text),
            "path": str(path.relative_to(PROJECT_ROOT)),
        })
    return rows


def normalize_proposal_status(raw: str | None) -> str:
    if not raw:
        return "unknown"
    value = raw.strip().lower()
    if value in {"draft", "under_review", "approved", "rejected", "parked", "pending_benchmark_review", "deferred"}:
        return value
    return "unknown"


def load_proposals() -> list[dict]:
    rows: list[dict] = []
    if not PROPOSALS_DIR.exists():
        return rows
    for path in sorted(PROPOSALS_DIR.glob("PR-*.md")):
        text = read_text(path)
        proposal_id = extract_field(text, "proposal_id") or path.stem
        proposed_name = extract_field(text, "proposed_name") or slugify(path.stem)
        status = normalize_proposal_status(extract_field(text, "status"))
        thesis = extract_section(text, "Structured thesis")
        validation_plan = extract_section(text, "Validation plan")
        failure_modes = extract_section(text, "Expected failure modes")
        open_questions = extract_section(text, "Open questions for review")
        approval_note = extract_section(text, "Approval note")
        category = classify_proposal_category(path, proposal_id, proposed_name, status, thesis, validation_plan)
        deferred_reason = extract_field(text, "deferred_reason") or None
        rows.append({
            "proposal_id": proposal_id,
            "date": extract_field(text, "date") or None,
            "proposed_by": extract_field(text, "proposed_by") or None,
            "strategy_name": proposed_name,
            "status": status,
            "deferred_reason": deferred_reason,
            "proposal_category": category,
            "plain_language_idea": extract_section(text, "Plain-language idea"),
            "thesis": thesis,
            "edge_type": extract_field(text, "edge_type") or None,
            "time_window": extract_field(text, "time_window") or None,
            "market_types": extract_field(text, "market_types") or None,
            "likely_inputs": extract_field(text, "likely_inputs") or None,
            "validation_plan": validation_plan,
            "expected_failure_modes": failure_modes,
            "open_questions": open_questions,
            "approval_note": approval_note,
            "approval_summary": summarize_proposal_approval(status, validation_plan, failure_modes, open_questions, approval_note),
            "path": str(path.relative_to(PROJECT_ROOT)),
        })
    return rows


def classify_proposal_category(path: Path, proposal_id: str, proposed_name: str, status: str, thesis: str, validation_plan: str) -> str:
    stem = path.stem.lower()
    name = (proposed_name or "").strip().lower()
    thesis_clean = (thesis or "").strip().lower()
    validation_clean = (validation_plan or "").strip().lower()

    if "live-trading-readiness" in stem or "live_trading_readiness" in name:
        return "non_strategy"
    if status == "unknown" and thesis_clean in {"", "what is the actual edge claim?"} and (not validation_clean or "paper window:" in validation_clean):
        return "cleanup"
    if name.startswith("pr_") and status == "unknown":
        return "non_strategy"
    return "strategy"


def summarize_proposal_approval(status: str, validation_plan: str, failure_modes: str, open_questions: str, approval_note: str) -> str:
    if status == "deferred":
        return "Deferred — revisit when conditions are met. Not rejected."
    if status == "pending_benchmark_review":
        if validation_plan:
            return "Validation in progress — evidence is being collected now before final approval. " + " ".join(validation_plan.split())[:240]
        return "Validation in progress — benchmark evidence is being collected before final approval."
    if status in {"draft", "under_review"}:
        if open_questions:
            return "Needs human review. " + " ".join(open_questions.split())[:240]
        return "Needs human review before approval."
    if status == "approved":
        if approval_note:
            return "Approved. " + " ".join(approval_note.split())[:240]
        return "Approved."
    if status == "rejected":
        return "Rejected."
    if status == "parked":
        return "Parked for later."
    if failure_modes:
        return " ".join(failure_modes.split())[:240]
    return "Status unclear; inspect proposal markdown."


def normalize_experiment_status(raw: str) -> str:
    if raw in {"running", "active"}:
        return "active"
    if raw in {"planned", "plan"}:
        return "planned"
    if raw in {"review_due", "review due"}:
        return "review_due"
    if raw in {"complete", "completed", "done"}:
        return "completed"
    if raw in {"archived", "archive"}:
        return "archived"
    return "unknown"


def infer_review_due(text: str) -> str | None:
    section = extract_section(text, "Validation window / method")
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", section)
    return m.group(1) if m else None


def summarize_experiment(text: str) -> str:
    for section in ["Before / after / observations", "Notes", "Hypothesis"]:
        value = extract_section(text, section)
        if value:
            return " ".join(value.split())[:240]
    return ""


def infer_strategy_from_text(text: str, fallback: str) -> str | None:
    candidates = sorted(ACTIVE_STRATEGIES | {"fade_certainty", "weather_edge"}, key=len, reverse=True)
    lower = text.lower() + " " + fallback.lower()
    for candidate in candidates:
        if candidate in lower:
            return candidate
    return None


def infer_experiment_scope(title: str, text: str, related_change_id: str | None, changes: dict[str, dict]) -> tuple[str, str, str | None]:
    change = changes.get(related_change_id or "", {})
    component = (change.get("component") or "")
    summary = (change.get("summary") or "")
    combined = "\n".join(filter(None, [title, text, component, summary]))
    hay = combined.lower()

    if any(term in hay for term in ["sqlite", "runtime", "storage", "observability", "db", "database"]):
        return "system", "runtime/storage", None
    if any(term in hay for term in ["taxonomy", "portfolio", "policy", "strategy stack", "focus", "active/legacy", "paused", "coherent edge classes"]):
        return "portfolio", (component or title), None

    strategy = infer_strategy_from_text(combined, title)
    if strategy:
        return "strategy", strategy, strategy

    return "unknown", title, None


def attach_linked_reviews(experiments: list[dict], reviews: dict[str, dict]) -> None:
    by_exp = defaultdict(list)
    for review_id, review in reviews.items():
        for experiment_id in review["related_experiment_ids"]:
            by_exp[experiment_id].append(review_id)
    for row in experiments:
        row["linked_reviews"] = sorted(by_exp.get(row["experiment_id"], []))
        if row["status"] in {"active", "planned"} and row["review_due"] is None and row["linked_reviews"]:
            row["status"] = "review_due"


def connect_db():
    if os.environ.get("DATABASE_URL"):
        return connect_compat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_runs(conn: object, limit: int = 25) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for row in rows:
        out.append({
            "run_id": row["id"],
            "started_at": row["started_at"],
            "duration_seconds": seconds_between(row["started_at"], row["finished_at"]),
            "status": normalize_status(row["status"]),
            "strategies_checked": count_distinct(conn, "SELECT COUNT(DISTINCT strategy) FROM decisions WHERE run_id = ?", (row["id"],)),
            "signals_generated": scalar(conn, "SELECT COUNT(*) FROM signals WHERE run_id = ?", (row["id"],), 0),
            "decisions_logged": scalar(conn, "SELECT COUNT(*) FROM decisions WHERE run_id = ?", (row["id"],), 0),
            "errors_count": scalar(conn, "SELECT COUNT(*) FROM run_logs WHERE run_id = ? AND level IN ('ERROR','CRITICAL')", (row["id"],), 0),
            "summary": summarize_run(row),
        })
    return out


def summarize_run(row: dict) -> str:
    status = normalize_status(row["status"])
    markets = row["markets_fetched"] or 0
    closed_count = row["closed_count"] or 0
    opened = row["new_positions_count"] or 0
    notes = (row["notes"] or "").strip()
    bits = [f"status={status}", f"markets={markets}", f"opened={opened}", f"closed={closed_count}"]
    if notes:
        bits.append(notes[:120])
    return "; ".join(bits)


def scalar(conn: object, sql: str, params: tuple = (), default=None):
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def file_size_bytes(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except FileNotFoundError:
        return 0


def dir_size_bytes(path: Path, *, excluded_dirs: set[str] | None = None) -> int:
    if not path.exists():
        return 0
    excluded_dirs = excluded_dirs or set()
    total = 0
    for child in path.rglob("*"):
        if any(part in excluded_dirs for part in child.parts):
            continue
        if child.is_file():
            total += file_size_bytes(child)
    return total


def count_distinct(conn: object, sql: str, params: tuple = ()) -> int:
    value = scalar(conn, sql, params, 0)
    return int(value or 0)


def fetch_execution_summary(conn: object) -> dict:
    checks_30d = scalar(conn, "SELECT COUNT(*) FROM signal_execution_checks WHERE created_at >= datetime('now', '-30 day')", (), 0)
    strategies_with_checks = scalar(conn, "SELECT COUNT(DISTINCT strategy) FROM signal_execution_checks WHERE created_at >= datetime('now', '-30 day')", (), 0)
    avg_ev_50 = scalar(conn, "SELECT AVG(ev_after_slippage_50_pp) FROM signal_execution_checks WHERE created_at >= datetime('now', '-30 day')", (), None)
    avg_max_positive = scalar(conn, "SELECT AVG(max_size_positive_ev) FROM signal_execution_checks WHERE created_at >= datetime('now', '-30 day')", (), None)
    confidence_rows = conn.execute(
        "SELECT COALESCE(source_confidence, 'unknown') AS source_confidence, COUNT(*) AS cnt FROM signal_execution_checks WHERE created_at >= datetime('now', '-30 day') GROUP BY COALESCE(source_confidence, 'unknown')"
    ).fetchall()
    return {
        "checks_30d": int(checks_30d or 0),
        "strategies_with_checks_30d": int(strategies_with_checks or 0),
        "avg_ev_after_slippage_50_pp_30d": round(float(avg_ev_50), 2) if avg_ev_50 is not None else None,
        "avg_max_size_positive_ev_30d": round(float(avg_max_positive), 2) if avg_max_positive is not None else None,
        "source_confidence_counts_30d": {row["source_confidence"]: int(row["cnt"] or 0) for row in confidence_rows},
    }


def fetch_storage(conn: object) -> dict:
    archive_rows = conn.execute(
        """
        SELECT run_id, created_at, event_count, LENGTH(payload_json) AS payload_bytes
        FROM market_snapshot_archives
        ORDER BY created_at DESC
        LIMIT 20
        """
    ).fetchall()
    archive_total_bytes = scalar(conn, "SELECT COALESCE(SUM(LENGTH(payload_json)), 0) FROM market_snapshot_archives", (), 0)
    archive_run_count = scalar(conn, "SELECT COUNT(*) FROM market_snapshot_archives", (), 0)
    observation_row_count = scalar(conn, "SELECT COUNT(*) FROM market_observations", (), 0)
    db_bytes = file_size_bytes(DB_PATH)
    benchmark_bytes = dir_size_bytes(BENCHMARK_DIR)
    dashboard_bytes = dir_size_bytes(OUTPUT_DIR)
    project_bytes = dir_size_bytes(PROJECT_ROOT, excluded_dirs=PROJECT_STORAGE_EXCLUDED_DIRS)
    disk_stat = os.statvfs(str(PROJECT_ROOT))
    disk_total = disk_stat.f_frsize * disk_stat.f_blocks
    disk_free = disk_stat.f_frsize * disk_stat.f_bavail
    disk_free_pct = disk_free / disk_total if disk_total else 1.0
    return {
        "generated_at": utc_now_iso(),
        "database_bytes": db_bytes,
        "benchmark_data_bytes": benchmark_bytes,
        "dashboard_data_bytes": dashboard_bytes,
        "project_storage_bytes": project_bytes,
        "disk_total_bytes": disk_total,
        "disk_free_bytes": disk_free,
        "disk_free_pct": round(disk_free_pct, 4),
        "disk_free_alert": disk_free_pct < DISK_FREE_ALERT_THRESHOLD,
        "raw_snapshot_archive_bytes": int(archive_total_bytes or 0),
        "raw_snapshot_archive_runs": int(archive_run_count or 0),
        "market_observation_rows": int(observation_row_count or 0),
        "raw_snapshot_retention_days": RAW_SNAPSHOT_RETENTION_DAYS,
        "recent_snapshot_archives": [
            {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "event_count": int(row["event_count"] or 0),
                "payload_bytes": int(row["payload_bytes"] or 0),
            }
            for row in archive_rows
        ][::-1],
    }


def load_benchmarks() -> dict:
    scopes = ("alert-only", "generated")
    data = {
        "generated_at": utc_now_iso(),
        "available_scopes": [],
        "scopes": {},
    }
    for scope in scopes:
        path = BENCHMARK_DIR / f"replay-benchmark-{scope}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["available_scopes"].append(scope)
        data["scopes"][scope] = payload
    return data


def _parse_generated_strategy_name(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return path.stem
    m = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else path.stem


def _proposal_payload_for_strategy(strategy_name: str) -> dict:
    if not PROPOSALS_DIR.exists():
        return {}
    slug = slugify(strategy_name)
    matches = sorted(PROPOSALS_DIR.glob(f"PR-*-{slug}.md"))
    if not matches:
        return {}
    path = matches[-1]
    text = read_text(path)
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "status": extract_field(text, "status") or None,
        "benchmark_gate_note": extract_section(text, "Benchmark gate note") or None,
    }


def load_generated_registry(benchmarks: dict | None = None) -> dict[str, dict]:
    generated_scores = {
        row.get("strategy"): row
        for row in ((benchmarks or {}).get("scopes", {}).get("generated", {}) or {}).get("strategies", [])
        if row.get("strategy")
    }
    rows: dict[str, dict] = {}

    def ingest_dir(base: Path, lifecycle: str) -> None:
        if not base.exists():
            return
        for path in sorted(base.glob("auto_*.py")):
            strategy_name = _parse_generated_strategy_name(path)
            proposal = _proposal_payload_for_strategy(strategy_name)
            benchmark_row = generated_scores.get(strategy_name, {})
            row = {
                "strategy_name": strategy_name,
                "module_path": str(path.relative_to(PROJECT_ROOT)),
                "generated_lifecycle": lifecycle if lifecycle == "archived" else (proposal.get("status") or "generated"),
                "proposal_path": proposal.get("path"),
                "archive_reason": proposal.get("benchmark_gate_note"),
                "generated_benchmark_score": benchmark_row.get("benchmark_score"),
                "generated_benchmark_signals": benchmark_row.get("signals"),
                "generated_benchmark_labeled": benchmark_row.get("labeled_signals"),
                "generated_benchmark_observed": benchmark_row.get("observed_signals"),
                "generated_benchmark_missing_forward": benchmark_row.get("no_forward_observation_signals"),
                "generated_benchmark_flat_observations": benchmark_row.get("flat_observation_signals"),
            }
            existing = rows.get(strategy_name)
            if lifecycle == "archived":
                if not existing:
                    rows[strategy_name] = row
            else:
                rows[strategy_name] = row

    ingest_dir(GENERATED_ARCHIVE_DIR, "archived")
    ingest_dir(GENERATED_DIR, "active")
    return rows


def fetch_overview(conn: object, experiments: list[dict], warnings: list[str], benchmarks: dict | None = None, storage: dict | None = None, strategy_factory: dict | None = None, strategy_factory_history: list[dict] | None = None) -> dict:
    latest = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    open_active_exposure = scalar(conn, "SELECT COALESCE(SUM(amount_usdc), 0) FROM trades WHERE status='open' AND strategy IN ({})".format(
        ",".join("?" for _ in ACTIVE_STRATEGIES)
    ), tuple(sorted(ACTIVE_STRATEGIES)), 0.0)
    open_active_count = scalar(conn, "SELECT COUNT(*) FROM trades WHERE status='open' AND strategy IN ({})".format(
        ",".join("?" for _ in ACTIVE_STRATEGIES)
    ), tuple(sorted(ACTIVE_STRATEGIES)), 0)
    open_legacy_exposure = scalar(conn, "SELECT COALESCE(SUM(amount_usdc), 0) FROM trades WHERE status='open' AND strategy NOT IN ({})".format(
        ",".join("?" for _ in ACTIVE_STRATEGIES)
    ), tuple(sorted(ACTIVE_STRATEGIES)), 0.0)
    open_legacy_count = scalar(conn, "SELECT COUNT(*) FROM trades WHERE status='open' AND strategy NOT IN ({})".format(
        ",".join("?" for _ in ACTIVE_STRATEGIES)
    ), tuple(sorted(ACTIVE_STRATEGIES)), 0)

    alerts = []
    if latest and normalize_status(latest["status"]) != "ok":
        alerts.append({"level": "warning", "message": f"Latest run status is {normalize_status(latest['status'])}."})
    if storage and storage.get("disk_free_alert"):
        disk_free_gb = float(storage.get("disk_free_bytes") or 0) / (1024 ** 3)
        disk_free_pct = float(storage.get("disk_free_pct") or 0) * 100
        alerts.append({
            "level": "warning",
            "message": f"Disk space low: {disk_free_gb:.1f} GB free ({disk_free_pct:.0f}%). Threshold is {DISK_FREE_ALERT_THRESHOLD * 100:.0f}%.",
        })
    for warning in warnings[:5]:
        alerts.append({"level": "warning", "message": warning})
    if strategy_factory:
        if strategy_factory.get("status") == "failed":
            alerts.append({
                "level": "error",
                "message": f"Strategy factory failed: {strategy_factory.get('error') or 'see latest run log'}",
            })
        elif strategy_factory.get("degraded"):
            alerts.append({
                "level": "warning",
                "message": f"Strategy factory degraded: using {strategy_factory.get('eval_source') or 'non-primary'} eval source.",
            })

    return {
        "generated_at": utc_now_iso(),
        "latest_run_status": normalize_status(latest["status"]) if latest else "unknown",
        "latest_run_started_at": latest["started_at"] if latest else None,
        "latest_run_duration_seconds": seconds_between(latest["started_at"], latest["finished_at"]) if latest else None,
        "open_exposure_active": round(float(open_active_exposure or 0.0), 2),
        "open_position_count_active": int(open_active_count or 0),
        "open_exposure_legacy": round(float(open_legacy_exposure or 0.0), 2),
        "open_position_count_legacy": int(open_legacy_count or 0),
        "strategy_factory": strategy_factory,
        "strategy_factory_history": strategy_factory_history or [],
        "alerts": alerts,
    }


def fetch_strategy_rows(conn: object) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            strategy,
            SUM(CASE WHEN status='open' THEN amount_usdc ELSE 0 END) AS open_exposure,
            SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_positions,
            SUM(CASE WHEN closed_at >= datetime('now', '-30 day') AND COALESCE(resolved_outcome, '') != 'CANCELLED' THEN pnl_usdc ELSE 0 END) AS realized_pnl_30d,
            SUM(CASE WHEN status='closed' AND COALESCE(resolved_outcome, '') != 'CANCELLED' THEN pnl_usdc ELSE 0 END) AS realized_pnl_all_time,
            SUM(CASE WHEN COALESCE(resolved_outcome, '') != 'CANCELLED' THEN 1 ELSE 0 END) AS trade_count,
            SUM(CASE WHEN resolved_outcome = 'CANCELLED' THEN 1 ELSE 0 END) AS cancelled_count
        FROM trades
        GROUP BY strategy
        ORDER BY strategy
        """
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_strategy_rows_by_mode(conn: object) -> dict[str, dict[str, dict]]:
    """Returns {strategy: {mode: {open_exposure, open_positions, closed_positions, realized_pnl_all_time}}}."""
    rows = conn.execute(
        """
        SELECT
            strategy,
            mode,
            SUM(CASE WHEN status='open' THEN amount_usdc ELSE 0 END) AS open_exposure,
            SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_positions,
            SUM(CASE WHEN status='closed' AND COALESCE(resolved_outcome, '') != 'CANCELLED' THEN 1 ELSE 0 END) AS closed_positions,
            SUM(CASE WHEN status='closed' AND COALESCE(resolved_outcome, '') != 'CANCELLED' THEN pnl_usdc ELSE 0 END) AS realized_pnl_all_time
        FROM trades
        WHERE mode IN ('paper', 'live')
        GROUP BY strategy, mode
        ORDER BY strategy, mode
        """
    ).fetchall()
    result: dict[str, dict[str, dict]] = {}
    for r in rows:
        d = dict(r)
        result.setdefault(d["strategy"], {})[d["mode"]] = {
            "open_exposure": round(float(d.get("open_exposure") or 0.0), 2),
            "open_positions": int(d.get("open_positions") or 0),
            "closed_positions": int(d.get("closed_positions") or 0),
            "realized_pnl_all_time": round(float(d.get("realized_pnl_all_time") or 0.0), 2),
        }
    return result


def fetch_positions_open(conn: object) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, strategy, market_title, outcome, amount_usdc, opened_at, url, status,
               lifecycle_group, time_window, edge_type
        FROM trades
        WHERE status='open'
        ORDER BY opened_at ASC
        """
    ).fetchall()
    out = []
    for row in rows:
        open_count = 1
        s_status = strategy_status(row["strategy"], open_count=open_count)
        item_warnings = []
        if not row["time_window"]:
            item_warnings.append("Missing time_window metadata.")
        if not row["edge_type"]:
            item_warnings.append("Missing edge_type metadata.")
        out.append({
            "position_id": row["id"],
            "strategy": row["strategy"],
            "strategy_status": s_status,
            "status": row["status"],
            "market": row["market_title"],
            "side": row["outcome"],
            "size": round(float(row["amount_usdc"] or 0.0), 2),
            "entry_time": row["opened_at"],
            "time_window": row["time_window"] or "unknown",
            "edge_type": row["edge_type"] or "unknown",
            "lifecycle_group": row["lifecycle_group"] or "unknown",
            "exposure": round(float(row["amount_usdc"] or 0.0), 2),
            "url": row["url"],
            "warnings": item_warnings,
        })
    return out


def fetch_strategies(conn: object, warnings: list[str], benchmarks: dict | None = None) -> list[dict]:
    meta_lookup = strategy_metadata()
    benchmark_scopes = (benchmarks or {}).get("scopes", {})
    alert_only_benchmark_rows = {
        row.get("strategy"): row for row in (benchmark_scopes.get("alert-only", {}) or {}).get("strategies", []) if row.get("strategy")
    }
    base = {row["strategy"]: row for row in fetch_strategy_rows(conn)}
    by_mode = fetch_strategy_rows_by_mode(conn)
    generated_registry = load_generated_registry(benchmarks)
    signal_counts = dict(conn.execute(
        "SELECT strategy, COUNT(*) FROM signals WHERE created_at >= datetime('now', '-30 day') GROUP BY strategy"
    ).fetchall())
    decision_counts = dict(conn.execute(
        "SELECT strategy, COUNT(*) FROM decisions WHERE created_at >= datetime('now', '-30 day') GROUP BY strategy"
    ).fetchall())
    execution_rows = conn.execute(
        """
        SELECT
            strategy,
            COUNT(*) AS execution_checks_count,
            AVG(ev_after_slippage_10_pp) AS avg_ev_after_slippage_10_pp,
            AVG(ev_after_slippage_50_pp) AS avg_ev_after_slippage_50_pp,
            AVG(ev_after_slippage_100_pp) AS avg_ev_after_slippage_100_pp,
            AVG(max_size_positive_ev) AS avg_max_size_positive_ev,
            AVG(max_size_above_min_edge) AS avg_max_size_above_min_edge
        FROM signal_execution_checks
        WHERE created_at >= datetime('now', '-30 day')
        GROUP BY strategy
        """
    ).fetchall()
    execution_by_strategy = {row["strategy"]: dict(row) for row in execution_rows}
    confidence_rows = conn.execute(
        "SELECT strategy, COALESCE(source_confidence, 'unknown') AS source_confidence, COUNT(*) AS cnt FROM signal_execution_checks WHERE created_at >= datetime('now', '-30 day') GROUP BY strategy, COALESCE(source_confidence, 'unknown')"
    ).fetchall()
    confidence_by_strategy = defaultdict(dict)
    for row in confidence_rows:
        confidence_by_strategy[row["strategy"]][row["source_confidence"]] = int(row["cnt"] or 0)

    tw_rows = conn.execute(
        "SELECT strategy, COALESCE(time_window, 'unknown') AS time_window, COUNT(*) AS cnt, COALESCE(SUM(amount_usdc),0) AS exposure FROM trades WHERE status='open' GROUP BY strategy, COALESCE(time_window, 'unknown')"
    ).fetchall()
    et_rows = conn.execute(
        "SELECT strategy, COALESCE(edge_type, 'unknown') AS edge_type, COUNT(*) AS cnt, COALESCE(SUM(amount_usdc),0) AS exposure FROM trades WHERE status='open' GROUP BY strategy, COALESCE(edge_type, 'unknown')"
    ).fetchall()

    by_tw = defaultdict(dict)
    for row in tw_rows:
        by_tw[row["strategy"]][row["time_window"]] = {
            "open_positions": int(row["cnt"] or 0),
            "open_exposure": round(float(row["exposure"] or 0.0), 2),
        }
    by_et = defaultdict(dict)
    for row in et_rows:
        by_et[row["strategy"]][row["edge_type"]] = {
            "open_positions": int(row["cnt"] or 0),
            "open_exposure": round(float(row["exposure"] or 0.0), 2),
        }

    all_names = sorted(set(base) | ACTIVE_STRATEGIES | set(generated_registry))
    out = []
    for name in all_names:
        row = base.get(name, {})
        meta = meta_lookup.get(name, {})
        open_positions = int(row.get("open_positions") or 0)
        generated_meta = generated_registry.get(name)
        benchmark_row = generated_meta or alert_only_benchmark_rows.get(name, {})
        status = generated_meta.get("generated_lifecycle") if generated_meta else strategy_status(name, open_count=open_positions)
        execution = execution_by_strategy.get(name, {})
        strategy_warnings = []
        if name not in base:
            strategy_warnings.append("No trades recorded yet.")
        if status != "active" and name in ACTIVE_STRATEGIES and open_positions == 0 and not signal_counts.get(name) and not decision_counts.get(name):
            strategy_warnings.append("Active strategy currently has no recent recorded activity.")
        if signal_counts.get(name, 0) and not execution.get("execution_checks_count"):
            strategy_warnings.append("Signals exist, but no Phase A execution checks were exported for the last 30 days.")
        if generated_meta and generated_meta.get("archive_reason"):
            strategy_warnings.append(generated_meta["archive_reason"])
        out.append({
            "strategy_name": name,
            "status": status,
            "is_generated": bool(generated_meta),
            "generated_lifecycle": generated_meta.get("generated_lifecycle") if generated_meta else None,
            "generated_module_path": generated_meta.get("module_path") if generated_meta else None,
            "generated_proposal_path": generated_meta.get("proposal_path") if generated_meta else None,
            "generated_archive_reason": generated_meta.get("archive_reason") if generated_meta else None,
            "generated_benchmark_score": generated_meta.get("generated_benchmark_score") if generated_meta else None,
            "generated_benchmark_signals": generated_meta.get("generated_benchmark_signals") if generated_meta else None,
            "generated_benchmark_labeled": generated_meta.get("generated_benchmark_labeled") if generated_meta else None,
            "generated_benchmark_observed": generated_meta.get("generated_benchmark_observed") if generated_meta else None,
            "generated_benchmark_missing_forward": generated_meta.get("generated_benchmark_missing_forward") if generated_meta else None,
            "generated_benchmark_flat_observations": generated_meta.get("generated_benchmark_flat_observations") if generated_meta else None,
            "benchmark_score": benchmark_row.get("benchmark_score"),
            "benchmark_signals": benchmark_row.get("signals"),
            "benchmark_observed_signals": benchmark_row.get("observed_signals"),
            "benchmark_missing_forward_signals": benchmark_row.get("no_forward_observation_signals"),
            "benchmark_flat_observation_signals": benchmark_row.get("flat_observation_signals"),
            "benchmark_labeled_signals": benchmark_row.get("labeled_signals"),
            "benchmark_observation_coverage": benchmark_row.get("observation_coverage"),
            "benchmark_label_coverage": benchmark_row.get("label_coverage"),
            "alert_only": bool(meta.get("alert_only", False)),
            "trading_enabled": bool(meta.get("trading_enabled", True)),
            "promotable": bool(meta.get("promotable", False)),
            "live_ready": bool(meta.get("live_ready", False)),
            "time_window": meta.get("time_window") or None,
            "edge_type": meta.get("edge_type") or None,
            "promotion_candidate": bool(meta.get("promotion_candidate", False)),
            "promotion_criteria": meta.get("promotion_criteria") or None,
            "open_exposure": round(float(row.get("open_exposure") or 0.0), 2),
            "open_positions": open_positions,
            "recent_signals_count": int(signal_counts.get(name, 0) or 0),
            "recent_decisions_count": int(decision_counts.get(name, 0) or 0),
            "realized_pnl_30d": round(float(row.get("realized_pnl_30d") or 0.0), 2),
            "realized_pnl_all_time": round(float(row.get("realized_pnl_all_time") or 0.0), 2),
            "by_mode": by_mode.get(name, {}),
            "execution_checks_count_30d": int(execution.get("execution_checks_count") or 0),
            "avg_ev_after_slippage_10_pp_30d": round(float(execution["avg_ev_after_slippage_10_pp"]), 2) if execution.get("avg_ev_after_slippage_10_pp") is not None else None,
            "avg_ev_after_slippage_50_pp_30d": round(float(execution["avg_ev_after_slippage_50_pp"]), 2) if execution.get("avg_ev_after_slippage_50_pp") is not None else None,
            "avg_ev_after_slippage_100_pp_30d": round(float(execution["avg_ev_after_slippage_100_pp"]), 2) if execution.get("avg_ev_after_slippage_100_pp") is not None else None,
            "avg_max_size_positive_ev_30d": round(float(execution["avg_max_size_positive_ev"]), 2) if execution.get("avg_max_size_positive_ev") is not None else None,
            "avg_max_size_above_min_edge_30d": round(float(execution["avg_max_size_above_min_edge"]), 2) if execution.get("avg_max_size_above_min_edge") is not None else None,
            "execution_source_confidence_counts_30d": confidence_by_strategy.get(name, {}),
            "by_time_window": by_tw.get(name, {}),
            "by_edge_type": by_et.get(name, {}),
            "warnings": strategy_warnings,
        })
    return out


def fetch_execution_checks(conn: object, limit: int = 250) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            created_at,
            run_id,
            strategy,
            market_id,
            market_title,
            outcome,
            quote_price,
            best_bid,
            best_ask,
            fill_price_10,
            fill_price_50,
            fill_price_100,
            ev_after_slippage_10_pp,
            ev_after_slippage_50_pp,
            ev_after_slippage_100_pp,
            max_size_positive_ev,
            max_size_above_min_edge,
            source_confidence
        FROM signal_execution_checks
        WHERE created_at >= datetime('now', '-30 day')
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "created_at": row["created_at"],
            "run_id": row["run_id"],
            "strategy": row["strategy"],
            "market_id": row["market_id"],
            "market_title": row["market_title"],
            "outcome": row["outcome"],
            "quote_price": round(float(row["quote_price"]), 4) if row["quote_price"] is not None else None,
            "best_bid": round(float(row["best_bid"]), 4) if row["best_bid"] is not None else None,
            "best_ask": round(float(row["best_ask"]), 4) if row["best_ask"] is not None else None,
            "fill_price_10": round(float(row["fill_price_10"]), 4) if row["fill_price_10"] is not None else None,
            "fill_price_50": round(float(row["fill_price_50"]), 4) if row["fill_price_50"] is not None else None,
            "fill_price_100": round(float(row["fill_price_100"]), 4) if row["fill_price_100"] is not None else None,
            "ev_after_slippage_10_pp": round(float(row["ev_after_slippage_10_pp"]), 2) if row["ev_after_slippage_10_pp"] is not None else None,
            "ev_after_slippage_50_pp": round(float(row["ev_after_slippage_50_pp"]), 2) if row["ev_after_slippage_50_pp"] is not None else None,
            "ev_after_slippage_100_pp": round(float(row["ev_after_slippage_100_pp"]), 2) if row["ev_after_slippage_100_pp"] is not None else None,
            "max_size_positive_ev": round(float(row["max_size_positive_ev"]), 2) if row["max_size_positive_ev"] is not None else None,
            "max_size_above_min_edge": round(float(row["max_size_above_min_edge"]), 2) if row["max_size_above_min_edge"] is not None else None,
            "source_confidence": row["source_confidence"] or "unknown",
        }
        for row in rows
    ]


def build_manifest(warnings: list[str], sqlite_available: bool, improvement_available: bool) -> dict:
    import socket
    return {
        "generated_at": utc_now_iso(),
        "export_version": "v1",
        "git_commit": get_git_commit(),
        "hostname": socket.gethostname(),
        "warning_count": len(warnings),
        "warnings": warnings,
        "source_summary": {
            "sqlite_available": sqlite_available,
            "improvement_records_available": improvement_available,
        },
    }


def collect_warnings(conn: object | None, changes: dict[str, dict], experiments: list[dict], reviews: dict[str, dict]) -> list[str]:
    warnings: list[str] = []
    for exp in experiments:
        for change_id in exp.get("linked_changes", []):
            if change_id and change_id not in changes:
                warnings.append(f"Experiment {exp['experiment_id']} links missing change record {change_id}.")
    for exp in experiments:
        if exp["scope_type"] == "unknown":
            warnings.append(f"Experiment {exp['experiment_id']} has unknown scope and needs metadata cleanup.")
    for review_id, review in reviews.items():
        for exp_id in review.get("related_experiment_ids", []):
            if exp_id and not any(e["experiment_id"] == exp_id for e in experiments):
                warnings.append(f"Review {review_id} links missing experiment {exp_id}.")
    if conn is not None:
        unknown_trade_rows = scalar(conn, "SELECT COUNT(*) FROM trades WHERE strategy IS NULL OR strategy = ''", (), 0)
        if unknown_trade_rows:
            warnings.append(f"Found {unknown_trade_rows} trade rows without strategy classification.")
    if any(row["status"] == "unknown" for row in experiments):
        warnings.append("Some experiments have unknown status and need better metadata.")
    deduped = []
    seen = set()
    for w in warnings:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    return deduped


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_run_history(conn: object, days: int = 14) -> dict:
    """Export run history for charting: per-pipeline daily counts + timeline."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # All runs in the window
    rows = conn.execute(
        "SELECT id, started_at, finished_at, mode, status, markets_fetched, new_positions_count, closed_count FROM runs WHERE started_at >= ? ORDER BY started_at",
        (cutoff,),
    ).fetchall()

    # Timeline: every run as a point
    timeline = []
    for row in rows:
        duration = seconds_between(row["started_at"], row["finished_at"])
        timeline.append({
            "started_at": row["started_at"],
            "mode": row["mode"] or "unknown",
            "status": normalize_status(row["status"]),
            "duration_seconds": duration,
            "markets_fetched": row["markets_fetched"] or 0,
            "new_positions": row["new_positions_count"] or 0,
            "closed": row["closed_count"] or 0,
        })

    # Daily aggregates by pipeline
    daily: dict[str, dict[str, dict]] = {}  # date -> pipeline -> {success, failed, total}
    pipeline_map = {
        "paper": "manual_combined",
        "paper_scan": "scanner",
        "paper_execute": "execute",
        "paper_dry_run": "manual_combined",
        "paper_fast_dry_run": "manual_combined",
        "observer": "observer",
        "trade_fetcher": "trade_fetcher",
    }
    for row in rows:
        date_str = (row["started_at"] or "")[:10]
        if not date_str:
            continue
        pipeline = pipeline_map.get(row["mode"] or "", "other")
        if date_str not in daily:
            daily[date_str] = {}
        if pipeline not in daily[date_str]:
            daily[date_str][pipeline] = {"success": 0, "failed": 0, "total": 0}
        daily[date_str][pipeline]["total"] += 1
        status = normalize_status(row["status"])
        if status in ("ok", "completed"):
            daily[date_str][pipeline]["success"] += 1
        elif status == "error":
            daily[date_str][pipeline]["failed"] += 1

    # Pipeline health (current)
    pipelines_config = [
        {"name": "scanner", "mode": "paper_scan", "expected_min": 150},
        {"name": "execute", "mode": "paper_execute", "expected_min": 150},
        {"name": "observer", "mode": "observer", "expected_min": 45},
        {"name": "trade_fetcher", "mode": "trade_fetcher", "expected_min": 45},
    ]
    health = []
    for p in pipelines_config:
        row = conn.execute(
            "SELECT finished_at, status FROM runs WHERE mode = ? ORDER BY started_at DESC LIMIT 1",
            (p["mode"],),
        ).fetchone()
        if not row or not row["finished_at"]:
            health.append({"name": p["name"], "status": "never_run", "age_minutes": None, "overdue": True})
        else:
            finished = parse_iso(row["finished_at"])
            age_min = int((datetime.now(timezone.utc) - finished).total_seconds() / 60) if finished else None
            health.append({
                "name": p["name"],
                "status": normalize_status(row["status"]),
                "last_run": row["finished_at"],
                "age_minutes": age_min,
                "overdue": age_min is not None and age_min > p["expected_min"],
            })

    return {
        "timeline": timeline,
        "daily": daily,
        "health": health,
        "days": days,
        "generated_at": utc_now_iso(),
    }


def main() -> None:
    ensure_output_dir()
    sqlite_available = DB_PATH.exists()
    improvement_available = IMPROVEMENT_DIR.exists()

    changes = load_changes() if CHANGES_DIR.exists() else {}
    reviews = load_reviews() if REVIEWS_DIR.exists() else {}
    experiments = load_experiments(changes) if EXPERIMENTS_DIR.exists() else []
    proposals = load_proposals() if PROPOSALS_DIR.exists() else []
    attach_linked_reviews(experiments, reviews)

    conn = connect_db() if sqlite_available else None
    warnings = collect_warnings(conn, changes, experiments, reviews)

    manifest = build_manifest(warnings, sqlite_available, improvement_available)
    write_json(OUTPUT_DIR / "manifest.json", manifest)

    if not sqlite_available:
        raise SystemExit("SQLite DB not found; wrote manifest with warning context only.")

    benchmarks = load_benchmarks()
    runs = fetch_runs(conn)
    strategies = fetch_strategies(conn, warnings, benchmarks)
    positions_open = fetch_positions_open(conn)
    strategy_factory = load_strategy_factory_status()
    strategy_factory_history = load_strategy_factory_history()
    overview = fetch_overview(conn, experiments, warnings, benchmarks, None, strategy_factory, strategy_factory_history)

    write_json(OUTPUT_DIR / "overview.json", overview)
    write_json(OUTPUT_DIR / "runs.json", runs)
    write_json(OUTPUT_DIR / "strategies.json", strategies)
    write_json(OUTPUT_DIR / "positions-open.json", positions_open)

    run_history = fetch_run_history(conn)
    write_json(OUTPUT_DIR / "run-history.json", run_history)

    print("Exported dashboard snapshot:")
    print(f"- manifest.json ({manifest['warning_count']} warning(s))")
    print(f"- overview.json")
    print(f"- runs.json ({len(runs)} rows)")
    print(f"- run-history.json ({len(run_history['timeline'])} runs, {len(run_history['daily'])} days)")
    print(f"- strategies.json ({len(strategies)} rows)")
    print(f"- positions-open.json ({len(positions_open)} rows)")

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()

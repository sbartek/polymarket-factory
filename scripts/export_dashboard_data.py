#!/usr/bin/env python3
"""Export reduced dashboard snapshot data for the PPLayouts external dashboard."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.db import FactoryDB
from factory.strategy_meta import strategy_metadata

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "factory.sqlite3"
OUTPUT_DIR = PROJECT_ROOT / "dashboard-data"
IMPROVEMENT_DIR = PROJECT_ROOT / "improvement"
CHANGES_DIR = IMPROVEMENT_DIR / "changes"
EXPERIMENTS_DIR = IMPROVEMENT_DIR / "experiments"
REVIEWS_DIR = IMPROVEMENT_DIR / "reviews"

ACTIVE_STRATEGIES = {
    "ev_news",
    "spread_arb",
    "resolution_hunter",
    "stale_market",
    "correlated_pairs",
    "correlated_laggard",
    "esport48",
}
TIME_WINDOWS = ["super_short", "intraday", "short", "medium", "long", "unknown"]


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
    if raw in {"warning", "warn", "partial"}:
        return "warning"
    if raw in {"error", "failed", "fail"}:
        return "error"
    return "unknown"


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
    m = re.search(rf"^- \*\*{re.escape(field)}:\*\*[ \t]*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def extract_section(text: str, heading: str) -> str:
    m = re.search(rf"## {re.escape(heading)}\n\n(.+?)(\n## |\Z)", text, re.S)
    return m.group(1).strip() if m else ""


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


def connect_db() -> sqlite3.Connection:
    return FactoryDB(path=DB_PATH)._connect()


def fetch_runs(conn: sqlite3.Connection, limit: int = 25) -> list[dict]:
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


def summarize_run(row: sqlite3.Row) -> str:
    status = normalize_status(row["status"])
    markets = row["markets_fetched"] or 0
    closed_count = row["closed_count"] or 0
    opened = row["new_positions_count"] or 0
    notes = (row["notes"] or "").strip()
    bits = [f"status={status}", f"markets={markets}", f"opened={opened}", f"closed={closed_count}"]
    if notes:
        bits.append(notes[:120])
    return "; ".join(bits)


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = (), default=None):
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def count_distinct(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    value = scalar(conn, sql, params, 0)
    return int(value or 0)


def fetch_execution_summary(conn: sqlite3.Connection) -> dict:
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


def fetch_overview(conn: sqlite3.Connection, experiments: list[dict], warnings: list[str]) -> dict:
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

    execution = fetch_execution_summary(conn)

    alerts = []
    if latest and normalize_status(latest["status"]) != "ok":
        alerts.append({"level": "warning", "message": f"Latest run status is {normalize_status(latest['status'])}."})
    if execution["checks_30d"] == 0:
        alerts.append({"level": "warning", "message": "No Phase A execution checks recorded in the last 30 days."})
    for warning in warnings[:5]:
        alerts.append({"level": "warning", "message": warning})

    return {
        "generated_at": utc_now_iso(),
        "latest_run_status": normalize_status(latest["status"]) if latest else "unknown",
        "latest_run_started_at": latest["started_at"] if latest else None,
        "latest_run_duration_seconds": seconds_between(latest["started_at"], latest["finished_at"]) if latest else None,
        "open_exposure_active": round(float(open_active_exposure or 0.0), 2),
        "open_position_count_active": int(open_active_count or 0),
        "open_exposure_legacy": round(float(open_legacy_exposure or 0.0), 2),
        "open_position_count_legacy": int(open_legacy_count or 0),
        "active_strategy_count": len(ACTIVE_STRATEGIES),
        "active_experiment_count": sum(1 for e in experiments if e["status"] in {"active", "review_due"}),
        "execution_checks_30d": execution["checks_30d"],
        "strategies_with_execution_checks_30d": execution["strategies_with_checks_30d"],
        "avg_ev_after_slippage_50_pp_30d": execution["avg_ev_after_slippage_50_pp_30d"],
        "avg_max_size_positive_ev_30d": execution["avg_max_size_positive_ev_30d"],
        "execution_source_confidence_counts_30d": execution["source_confidence_counts_30d"],
        "alerts": alerts,
    }


def fetch_strategy_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            strategy,
            SUM(CASE WHEN status='open' THEN amount_usdc ELSE 0 END) AS open_exposure,
            SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_positions,
            SUM(CASE WHEN closed_at >= datetime('now', '-30 day') THEN pnl_usdc ELSE 0 END) AS realized_pnl_30d,
            SUM(CASE WHEN status='closed' THEN pnl_usdc ELSE 0 END) AS realized_pnl_all_time,
            COUNT(*) AS trade_count
        FROM trades
        GROUP BY strategy
        ORDER BY strategy
        """
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_positions_open(conn: sqlite3.Connection) -> list[dict]:
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


def fetch_strategies(conn: sqlite3.Connection, warnings: list[str]) -> list[dict]:
    meta_lookup = strategy_metadata()
    base = {row["strategy"]: row for row in fetch_strategy_rows(conn)}
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

    all_names = sorted(set(base) | ACTIVE_STRATEGIES)
    out = []
    for name in all_names:
        row = base.get(name, {})
        meta = meta_lookup.get(name, {})
        open_positions = int(row.get("open_positions") or 0)
        status = strategy_status(name, open_count=open_positions)
        execution = execution_by_strategy.get(name, {})
        strategy_warnings = []
        if name not in base:
            strategy_warnings.append("No trades recorded yet.")
        if status != "active" and name in ACTIVE_STRATEGIES and open_positions == 0 and not signal_counts.get(name) and not decision_counts.get(name):
            strategy_warnings.append("Active strategy currently has no recent recorded activity.")
        if signal_counts.get(name, 0) and not execution.get("execution_checks_count"):
            strategy_warnings.append("Signals exist, but no Phase A execution checks were exported for the last 30 days.")
        out.append({
            "strategy_name": name,
            "status": status,
            "alert_only": bool(meta.get("alert_only", False)),
            "trading_enabled": bool(meta.get("trading_enabled", True)),
            "promotable": bool(meta.get("promotable", False)),
            "live_ready": bool(meta.get("live_ready", False)),
            "promotion_candidate": bool(meta.get("promotion_candidate", False)),
            "promotion_criteria": meta.get("promotion_criteria") or None,
            "open_exposure": round(float(row.get("open_exposure") or 0.0), 2),
            "open_positions": open_positions,
            "recent_signals_count": int(signal_counts.get(name, 0) or 0),
            "recent_decisions_count": int(decision_counts.get(name, 0) or 0),
            "realized_pnl_30d": round(float(row.get("realized_pnl_30d") or 0.0), 2),
            "realized_pnl_all_time": round(float(row.get("realized_pnl_all_time") or 0.0), 2),
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


def fetch_execution_checks(conn: sqlite3.Connection, limit: int = 250) -> list[dict]:
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
    return {
        "generated_at": utc_now_iso(),
        "export_version": "v1",
        "git_commit": get_git_commit(),
        "warning_count": len(warnings),
        "warnings": warnings,
        "source_summary": {
            "sqlite_available": sqlite_available,
            "improvement_records_available": improvement_available,
        },
    }


def collect_warnings(conn: sqlite3.Connection | None, changes: dict[str, dict], experiments: list[dict], reviews: dict[str, dict]) -> list[str]:
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


def main() -> None:
    ensure_output_dir()
    sqlite_available = DB_PATH.exists()
    improvement_available = IMPROVEMENT_DIR.exists()

    changes = load_changes() if CHANGES_DIR.exists() else {}
    reviews = load_reviews() if REVIEWS_DIR.exists() else {}
    experiments = load_experiments(changes) if EXPERIMENTS_DIR.exists() else []
    attach_linked_reviews(experiments, reviews)

    conn = connect_db() if sqlite_available else None
    warnings = collect_warnings(conn, changes, experiments, reviews)

    manifest = build_manifest(warnings, sqlite_available, improvement_available)
    write_json(OUTPUT_DIR / "manifest.json", manifest)

    if not sqlite_available:
        raise SystemExit("SQLite DB not found; wrote manifest with warning context only.")

    overview = fetch_overview(conn, experiments, warnings)
    runs = fetch_runs(conn)
    strategies = fetch_strategies(conn, warnings)
    execution_checks = fetch_execution_checks(conn)
    positions_open = fetch_positions_open(conn)

    write_json(OUTPUT_DIR / "overview.json", overview)
    write_json(OUTPUT_DIR / "runs.json", runs)
    write_json(OUTPUT_DIR / "strategies.json", strategies)
    write_json(OUTPUT_DIR / "execution-checks.json", execution_checks)
    write_json(OUTPUT_DIR / "experiments.json", experiments)
    write_json(OUTPUT_DIR / "positions-open.json", positions_open)

    print("Exported dashboard snapshot:")
    print(f"- manifest.json ({manifest['warning_count']} warning(s))")
    print(f"- overview.json")
    print(f"- runs.json ({len(runs)} rows)")
    print(f"- strategies.json ({len(strategies)} rows)")
    print(f"- execution-checks.json ({len(execution_checks)} rows)")
    print(f"- experiments.json ({len(experiments)} rows)")
    print(f"- positions-open.json ({len(positions_open)} rows)")

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()

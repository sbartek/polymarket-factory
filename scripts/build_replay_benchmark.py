#!/usr/bin/env python3
"""Build a replay benchmark summary from persisted signal and execution evidence."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory.db import DB_PATH
from factory.strategies import STRATEGIES
from factory.strategy_meta import strategy_metadata

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "benchmark-data"

MIN_SIGNALS_DEFAULT = 5
MIN_LABELED_DEFAULT = 3


@dataclass
class BenchmarkRow:
    strategy: str
    run_id: str
    signal_id: int
    created_at: str
    market_id: str
    market_title: str
    outcome: str
    market_price: float
    ev_pp: float
    confidence: str
    time_window: str
    edge_type: str
    ev_after_slippage_10_pp: float | None
    ev_after_slippage_25_pp: float | None
    max_size_positive_ev: float | None
    max_size_above_min_edge: float | None
    source_confidence: str
    overlap_count: int
    is_labeled: bool
    is_correct: bool | None
    label_source: str
    label_target_at: str = ""
    future_observed_at: str = ""
    future_yes_price: float | None = None
    price_move_pp: float | None = None


SLICE_UNKNOWN = "unknown"
PRICE_WINDOW_LABEL_SOURCE = "price_window"
PRICE_MOVE_THRESHOLD = 0.02


@dataclass(frozen=True)
class PriceObservation:
    market_id: str
    observed_at: str
    yes_price: float
    source: str


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def pp_to_unit(value: float | None, floor: float = -5.0, ceiling: float = 15.0) -> float:
    if value is None:
        return 0.0
    if ceiling <= floor:
        return 0.0
    return clamp((value - floor) / (ceiling - floor))


def mean(values: list[float | None]) -> float | None:
    keep = [float(v) for v in values if v is not None]
    if not keep:
        return None
    return sum(keep) / len(keep)


def source_confidence_score(label: str | None) -> float:
    mapping = {
        "very_low": 0.2,
        "low": 0.4,
        "medium": 0.7,
        "high": 1.0,
    }
    return mapping.get((label or "").lower(), 0.3)


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_yes_price(outcome: str | None, price: float | None) -> float | None:
    if price is None:
        return None
    outcome_value = (outcome or "").upper()
    if outcome_value == "NO":
        return clamp(1.0 - float(price))
    return clamp(float(price))


def window_bounds_for_row(row: BenchmarkRow, meta: dict[str, dict]) -> tuple[datetime | None, datetime | None]:
    created_at = parse_iso(row.created_at)
    if created_at is None:
        return None, None
    strategy_meta = meta.get(row.strategy, {})
    min_days = float(strategy_meta.get("target_hold_min_days") or 0)
    max_days = float(strategy_meta.get("target_hold_max_days") or 0)
    if max_days <= 0:
        fallback = {
            "super_short": (0.0, 1 / 24),
            "intraday": (1 / 24, 1.0),
            "short": (1.0, 7.0),
            "medium": (8.0, 30.0),
            "long": (31.0, 90.0),
        }.get((row.time_window or "").strip().lower(), (0.0, 7.0))
        min_days, max_days = fallback
    if max_days < min_days:
        max_days = min_days
    return created_at + timedelta(days=min_days), created_at + timedelta(days=max_days)


def load_price_observations(conn: sqlite3.Connection, *, since: str | None = None) -> dict[str, list[PriceObservation]]:
    clauses = []
    params: list[object] = []
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    observation_clauses = list(clauses)
    observation_clauses.append("yes_price IS NOT NULL")
    observation_where = f"WHERE {' AND '.join(observation_clauses)}"
    observations: dict[str, list[PriceObservation]] = {}
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'market_observations'"
    ).fetchone() is not None
    if table_exists:
        query = f"""
        SELECT market_id, created_at AS observed_at, yes_price, 'market_observation' AS source
        FROM market_observations
        {observation_where}
        ORDER BY market_id ASC, observed_at ASC
        """
        for row in conn.execute(query, tuple(params)):
            yes_price = _safe_float(row["yes_price"])
            if yes_price is None:
                continue
            observations.setdefault(row["market_id"], []).append(
                PriceObservation(
                    market_id=row["market_id"],
                    observed_at=row["observed_at"],
                    yes_price=clamp(yes_price),
                    source=row["source"],
                )
            )
    if observations:
        return observations

    fallback_query = f"""
    SELECT market_id, observed_at, outcome, price, source FROM (
        SELECT market_id, created_at AS observed_at, outcome, market_price AS price, 'signal' AS source
        FROM signals
        {where}
        UNION ALL
        SELECT market_id, created_at AS observed_at, outcome, quote_price AS price, 'execution_check' AS source
        FROM signal_execution_checks
        {where}
    )
    WHERE price IS NOT NULL
    ORDER BY market_id ASC, observed_at ASC
    """
    bind = tuple(params + params)
    for row in conn.execute(fallback_query, bind):
        yes_price = normalize_yes_price(row["outcome"], _safe_float(row["price"]))
        if yes_price is None:
            continue
        observations.setdefault(row["market_id"], []).append(
            PriceObservation(
                market_id=row["market_id"],
                observed_at=row["observed_at"],
                yes_price=yes_price,
                source=row["source"],
            )
        )
    return observations


def apply_price_window_labels(
    rows: list[BenchmarkRow],
    *,
    observations_by_market: dict[str, list[PriceObservation]],
    meta: dict[str, dict],
    move_threshold: float = PRICE_MOVE_THRESHOLD,
) -> None:
    for row in rows:
        if row.is_labeled:
            continue
        entry_yes_price = normalize_yes_price(row.outcome, row.market_price)
        if entry_yes_price is None:
            continue
        created_at = parse_iso(row.created_at)
        if created_at is None:
            continue
        window_start, window_end = window_bounds_for_row(row, meta)
        if window_start is None or window_end is None:
            continue
        candidates = []
        for observation in observations_by_market.get(row.market_id, []):
            observed_at = parse_iso(observation.observed_at)
            if observed_at is None or observed_at <= created_at:
                continue
            if observed_at > window_end:
                break
            if observed_at >= window_start:
                candidates.append((abs((window_end - observed_at).total_seconds()), observation))
        if not candidates:
            continue
        _, chosen = min(candidates, key=lambda item: item[0])
        move = chosen.yes_price - entry_yes_price
        signed_move = move if (row.outcome or "").upper() == "YES" else -move
        row.is_labeled = True
        row.is_correct = signed_move >= move_threshold
        row.label_source = PRICE_WINDOW_LABEL_SOURCE
        row.label_target_at = window_end.isoformat(timespec="seconds")
        row.future_observed_at = chosen.observed_at
        row.future_yes_price = round(chosen.yes_price, 4)
        row.price_move_pp = round(signed_move * 100, 2)


def generated_strategy_names() -> set[str]:
    names: set[str] = set()
    for strategy in STRATEGIES:
        module_name = type(strategy).__module__
        if ".generated." in module_name:
            names.add(strategy.name)
    return names


def load_rows(
    conn: sqlite3.Connection,
    *,
    strategy_names: set[str] | None = None,
    since: str | None = None,
) -> list[BenchmarkRow]:
    clauses = []
    params: list[object] = []
    if strategy_names:
        placeholders = ", ".join("?" for _ in strategy_names)
        clauses.append(f"s.strategy IN ({placeholders})")
        params.extend(sorted(strategy_names))
    if since:
        clauses.append("s.created_at >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    query = f"""
    WITH signal_ranked AS (
        SELECT
            s.*,
            ROW_NUMBER() OVER (
                PARTITION BY s.run_id, s.strategy, s.market_id, s.outcome
                ORDER BY s.id
            ) AS pair_n
        FROM signals s
        {where}
    ),
    exec_ranked AS (
        SELECT
            e.*,
            ROW_NUMBER() OVER (
                PARTITION BY e.run_id, e.strategy, e.market_id, e.outcome
                ORDER BY e.id
            ) AS pair_n
        FROM signal_execution_checks e
    ),
    resolved_markets AS (
        SELECT
            market_id,
            resolved_outcome,
            CASE
                WHEN SUM(CASE WHEN resolved_outcome IS NOT NULL AND resolved_outcome != '' THEN 1 ELSE 0 END) > 0
                THEN 'trade_resolution'
                ELSE ''
            END AS label_source
        FROM trades
        WHERE status = 'closed'
          AND resolved_outcome IS NOT NULL
          AND resolved_outcome != ''
        GROUP BY market_id, resolved_outcome
    ),
    overlaps AS (
        SELECT
            run_id,
            market_id,
            outcome,
            COUNT(DISTINCT strategy) AS strategy_count
        FROM signals
        GROUP BY run_id, market_id, outcome
    )
    SELECT
        s.id AS signal_id,
        s.run_id,
        s.strategy,
        s.created_at,
        s.market_id,
        s.market_title,
        s.outcome,
        s.market_price,
        s.ev_pp,
        s.confidence,
        COALESCE(s.time_window, '') AS time_window,
        COALESCE(s.edge_type, '') AS edge_type,
        e.ev_after_slippage_10_pp,
        e.ev_after_slippage_25_pp,
        e.max_size_positive_ev,
        e.max_size_above_min_edge,
        COALESCE(e.source_confidence, '') AS source_confidence,
        CASE WHEN o.strategy_count IS NULL THEN 0 ELSE MAX(o.strategy_count - 1, 0) END AS overlap_count,
        r.resolved_outcome,
        COALESCE(r.label_source, '') AS label_source
    FROM signal_ranked s
    LEFT JOIN exec_ranked e
      ON e.run_id = s.run_id
     AND e.strategy = s.strategy
     AND e.market_id = s.market_id
     AND e.outcome = s.outcome
     AND e.pair_n = s.pair_n
    LEFT JOIN overlaps o
      ON o.run_id = s.run_id
     AND o.market_id = s.market_id
     AND o.outcome = s.outcome
    LEFT JOIN resolved_markets r
      ON r.market_id = s.market_id
    ORDER BY s.created_at ASC, s.id ASC
    """

    rows: list[BenchmarkRow] = []
    for row in conn.execute(query, params):
        resolved_outcome = row["resolved_outcome"]
        is_labeled = bool(resolved_outcome)
        is_correct = None if not is_labeled else resolved_outcome == row["outcome"]
        rows.append(
            BenchmarkRow(
                strategy=row["strategy"],
                run_id=row["run_id"],
                signal_id=int(row["signal_id"]),
                created_at=row["created_at"],
                market_id=row["market_id"],
                market_title=row["market_title"],
                outcome=row["outcome"],
                market_price=float(row["market_price"] or 0.0),
                ev_pp=float(row["ev_pp"] or 0.0),
                confidence=row["confidence"] or "",
                time_window=row["time_window"] or "",
                edge_type=row["edge_type"] or "",
                ev_after_slippage_10_pp=None if row["ev_after_slippage_10_pp"] is None else float(row["ev_after_slippage_10_pp"]),
                ev_after_slippage_25_pp=None if row["ev_after_slippage_25_pp"] is None else float(row["ev_after_slippage_25_pp"]),
                max_size_positive_ev=None if row["max_size_positive_ev"] is None else float(row["max_size_positive_ev"]),
                max_size_above_min_edge=None if row["max_size_above_min_edge"] is None else float(row["max_size_above_min_edge"]),
                source_confidence=row["source_confidence"] or "",
                overlap_count=int(row["overlap_count"] or 0),
                is_labeled=is_labeled,
                is_correct=is_correct,
                label_source=row["label_source"] or "",
            )
        )
    return rows


def summarize_strategy(
    strategy: str,
    rows: list[BenchmarkRow],
    *,
    min_signals: int,
    min_labeled: int,
) -> dict:
    total = len(rows)
    labeled = [row for row in rows if row.is_labeled]
    labeled_count = len(labeled)
    correct_count = sum(1 for row in labeled if row.is_correct)
    correctness_rate = (correct_count / labeled_count) if labeled_count else 0.5
    label_shrink = clamp(labeled_count / max(min_labeled, 1))
    directional_score = 0.5 + (correctness_rate - 0.5) * label_shrink

    avg_ev_10 = mean([row.ev_after_slippage_10_pp for row in rows])
    avg_ev_25 = mean([row.ev_after_slippage_25_pp for row in rows])
    slippage_score = mean([pp_to_unit(avg_ev_10), pp_to_unit(avg_ev_25)]) or 0.0

    avg_capacity = mean([row.max_size_positive_ev for row in rows]) or 0.0
    avg_above_min = mean([row.max_size_above_min_edge for row in rows]) or 0.0
    capacity_size_score = clamp(mean([avg_capacity / 25.0, avg_above_min / 25.0]) or 0.0)
    confidence_score = mean([source_confidence_score(row.source_confidence) for row in rows]) or 0.0
    capacity_score = mean([capacity_size_score, confidence_score]) or 0.0

    duplicate_rate = sum(1 for row in rows if row.overlap_count > 0) / total if total else 0.0
    uniqueness_score = 1.0 - duplicate_rate
    coverage_score = clamp(total / max(min_signals, 1))

    benchmark_score = (
        0.45 * directional_score
        + 0.25 * slippage_score
        + 0.15 * capacity_score
        + 0.10 * uniqueness_score
        + 0.05 * coverage_score
    )

    return {
        "strategy": strategy,
        "signals": total,
        "labeled_signals": labeled_count,
        "correct_signals": correct_count,
        "correctness_rate": round(correctness_rate, 4),
        "directional_score": round(directional_score, 4),
        "avg_ev_after_slippage_10_pp": None if avg_ev_10 is None else round(avg_ev_10, 3),
        "avg_ev_after_slippage_25_pp": None if avg_ev_25 is None else round(avg_ev_25, 3),
        "slippage_score": round(slippage_score, 4),
        "avg_max_size_positive_ev": round(avg_capacity, 2),
        "avg_max_size_above_min_edge": round(avg_above_min, 2),
        "avg_source_confidence_score": round(confidence_score, 4),
        "capacity_score": round(capacity_score, 4),
        "duplicate_rate": round(duplicate_rate, 4),
        "uniqueness_score": round(uniqueness_score, 4),
        "coverage_score": round(coverage_score, 4),
        "benchmark_score": round(benchmark_score, 4),
        "label_sources": sorted({row.label_source for row in labeled if row.label_source}),
    }


def normalize_slice_value(value: str | None) -> str:
    cleaned = (value or "").strip()
    return cleaned or SLICE_UNKNOWN


def summarize_slice(
    strategy: str,
    rows: list[BenchmarkRow],
    *,
    time_window: str,
    edge_type: str,
    min_signals: int,
    min_labeled: int,
) -> dict:
    summary = summarize_strategy(strategy, rows, min_signals=min_signals, min_labeled=min_labeled)
    summary["time_window"] = normalize_slice_value(time_window)
    summary["edge_type"] = normalize_slice_value(edge_type)
    summary["slice_key"] = f"{summary['edge_type']}::{summary['time_window']}"
    return summary


def build_summary(
    rows: list[BenchmarkRow],
    *,
    scope: str,
    min_signals: int,
    min_labeled: int,
) -> dict:
    strategies = sorted({row.strategy for row in rows})
    summaries = [
        summarize_strategy(strategy, [row for row in rows if row.strategy == strategy], min_signals=min_signals, min_labeled=min_labeled)
        for strategy in strategies
    ]
    summaries.sort(key=lambda row: row["benchmark_score"], reverse=True)
    slice_summaries = []
    for strategy in strategies:
        strategy_rows = [row for row in rows if row.strategy == strategy]
        buckets: dict[tuple[str, str], list[BenchmarkRow]] = {}
        for row in strategy_rows:
            key = (normalize_slice_value(row.edge_type), normalize_slice_value(row.time_window))
            buckets.setdefault(key, []).append(row)
        for (edge_type, time_window), bucket_rows in sorted(buckets.items()):
            slice_summaries.append(
                summarize_slice(
                    strategy,
                    bucket_rows,
                    time_window=time_window,
                    edge_type=edge_type,
                    min_signals=min_signals,
                    min_labeled=min_labeled,
                )
            )
    slice_summaries.sort(key=lambda row: (row["strategy"], -row["benchmark_score"], row["edge_type"], row["time_window"]))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": scope,
        "min_signals": min_signals,
        "min_labeled": min_labeled,
        "strategy_count": len(summaries),
        "signal_count": len(rows),
        "strategies": summaries,
        "slice_count": len(slice_summaries),
        "strategy_slices": slice_summaries,
    }


def strategy_scope_names(scope: str) -> tuple[set[str], dict[str, dict]]:
    meta = strategy_metadata()
    generated = generated_strategy_names()
    with_signals = set(meta)
    if scope == "generated":
        return generated, meta
    if scope == "alert-only":
        return {name for name, row in meta.items() if row.get("alert_only") or name in generated}, meta
    return with_signals, meta


def render_table(summary: dict) -> str:
    lines = []
    lines.append(
        "strategy".ljust(24)
        + "score".rjust(8)
        + "  "
        + "dir".rjust(6)
        + "  "
        + "ev10".rjust(7)
        + "  "
        + "cap".rjust(6)
        + "  "
        + "uniq".rjust(6)
        + "  "
        + "cov".rjust(6)
        + "  "
        + "labels".rjust(8)
        + "  "
        + "signals".rjust(7)
    )
    lines.append("-" * len(lines[0]))
    for row in summary["strategies"]:
        lines.append(
            row["strategy"][:24].ljust(24)
            + f"{row['benchmark_score']:>8.3f}"
            + "  "
            + f"{row['directional_score']:>6.3f}"
            + "  "
            + f"{(row['avg_ev_after_slippage_10_pp'] if row['avg_ev_after_slippage_10_pp'] is not None else 0.0):>7.2f}"
            + "  "
            + f"{row['capacity_score']:>6.3f}"
            + "  "
            + f"{row['uniqueness_score']:>6.3f}"
            + "  "
            + f"{row['coverage_score']:>6.3f}"
            + "  "
            + f"{row['labeled_signals']:>8}"
            + "  "
            + f"{row['signals']:>7}"
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a replay benchmark from logged factory evidence.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite DB path")
    parser.add_argument("--scope", choices=("alert-only", "generated", "all"), default="alert-only", help="Strategies to benchmark")
    parser.add_argument("--since", default=None, help="Only include signals created at or after this ISO timestamp")
    parser.add_argument("--min-signals", type=int, default=MIN_SIGNALS_DEFAULT, help="Coverage target for full score")
    parser.add_argument("--min-labeled", type=int, default=MIN_LABELED_DEFAULT, help="Labeled sample target before directional score is trusted")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON summary to this path")
    parser.add_argument("--include-rows", action="store_true", help="Include row-level evidence in JSON output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.db.exists():
        print(f"Database not found: {args.db}")
        raise SystemExit(1)

    strategy_names, meta = strategy_scope_names(args.scope)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_rows(conn, strategy_names=strategy_names, since=args.since)
    observations_by_market = load_price_observations(conn, since=args.since)

    if args.scope != "all":
        rows = [row for row in rows if row.strategy in strategy_names]

    apply_price_window_labels(rows, observations_by_market=observations_by_market, meta=meta)
    summary = build_summary(rows, scope=args.scope, min_signals=args.min_signals, min_labeled=args.min_labeled)
    summary["strategy_metadata"] = {
        row["strategy"]: {
            "edge_type": meta.get(row["strategy"], {}).get("edge_type"),
            "time_window": meta.get(row["strategy"], {}).get("time_window"),
            "alert_only": meta.get(row["strategy"], {}).get("alert_only"),
            "promotable": meta.get(row["strategy"], {}).get("promotable"),
        }
        for row in summary["strategies"]
    }
    if args.include_rows:
        summary["rows"] = [asdict(row) for row in rows]

    print(f"Replay benchmark — scope={args.scope} — {summary['signal_count']} signals across {summary['strategy_count']} strategies\n")
    if summary["strategies"]:
        print(render_table(summary))
    else:
        print("No matching signals found.")

    output_path = args.output
    if output_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"replay-benchmark-{args.scope}.json"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()

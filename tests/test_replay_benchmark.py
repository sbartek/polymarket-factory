from scripts.build_replay_benchmark import (
    BenchmarkRow,
    PriceObservation,
    apply_price_window_labels,
    build_summary,
    load_price_observations,
)
import sqlite3


def _row(
    strategy: str,
    *,
    signal_id: int,
    is_correct: bool | None,
    overlap_count: int = 0,
    ev10: float | None = 8.0,
    ev25: float | None = 6.0,
    max_positive: float | None = 25.0,
    max_above_min: float | None = 25.0,
    source_confidence: str = "high",
) -> BenchmarkRow:
    return BenchmarkRow(
        strategy=strategy,
        run_id="run-1",
        signal_id=signal_id,
        created_at="2026-04-03T12:00:00",
        market_id=f"market-{signal_id}",
        market_title="Example",
        outcome="YES",
        market_price=0.4,
        ev_pp=12.0,
        confidence="high",
        time_window="short",
        edge_type="other",
        ev_after_slippage_10_pp=ev10,
        ev_after_slippage_25_pp=ev25,
        max_size_positive_ev=max_positive,
        max_size_above_min_edge=max_above_min,
        source_confidence=source_confidence,
        overlap_count=overlap_count,
        is_labeled=is_correct is not None,
        is_correct=is_correct,
        label_source="trade_resolution" if is_correct is not None else "",
    )


def test_build_summary_rewards_higher_quality_strategies():
    rows = [
        _row("alpha", signal_id=1, is_correct=True, overlap_count=0, ev10=9.0, ev25=7.0, max_positive=25.0, max_above_min=25.0),
        _row("alpha", signal_id=2, is_correct=True, overlap_count=0, ev10=8.0, ev25=6.0, max_positive=25.0, max_above_min=25.0),
        _row("alpha", signal_id=3, is_correct=True, overlap_count=0, ev10=7.5, ev25=5.5, max_positive=25.0, max_above_min=25.0),
        _row("beta", signal_id=4, is_correct=False, overlap_count=1, ev10=-2.0, ev25=-3.0, max_positive=5.0, max_above_min=0.0, source_confidence="low"),
        _row("beta", signal_id=5, is_correct=False, overlap_count=1, ev10=-1.0, ev25=-2.0, max_positive=10.0, max_above_min=0.0, source_confidence="low"),
        _row("beta", signal_id=6, is_correct=True, overlap_count=1, ev10=0.0, ev25=-1.0, max_positive=10.0, max_above_min=0.0, source_confidence="low"),
    ]
    summary = build_summary(rows, scope="all", min_signals=3, min_labeled=3)
    assert summary["strategies"][0]["strategy"] == "alpha"
    assert summary["strategies"][1]["strategy"] == "beta"
    assert summary["strategies"][0]["benchmark_score"] > summary["strategies"][1]["benchmark_score"]


def test_directional_score_shrinks_toward_neutral_with_tiny_label_count():
    rows = [
        _row("alpha", signal_id=1, is_correct=True),
        _row("alpha", signal_id=2, is_correct=None),
        _row("alpha", signal_id=3, is_correct=None),
        _row("alpha", signal_id=4, is_correct=None),
        _row("alpha", signal_id=5, is_correct=None),
    ]
    summary = build_summary(rows, scope="all", min_signals=5, min_labeled=4)
    alpha = summary["strategies"][0]
    assert alpha["labeled_signals"] == 1
    assert 0.5 < alpha["directional_score"] < 0.7


def test_build_summary_emits_strategy_slice_breakdowns():
    rows = [
        _row("alpha", signal_id=1, is_correct=True),
        _row("alpha", signal_id=2, is_correct=True),
        _row("alpha", signal_id=3, is_correct=False),
    ]
    rows[1].time_window = "medium"
    rows[2].edge_type = "momentum"
    rows[2].time_window = "medium"

    summary = build_summary(rows, scope="all", min_signals=2, min_labeled=2)

    assert summary["slice_count"] == 3
    assert summary["strategy_slices"][0]["strategy"] == "alpha"
    assert summary["strategy_slices"][0]["slice_key"]
    slices = {(row["edge_type"], row["time_window"]): row for row in summary["strategy_slices"]}
    assert ("other", "short") in slices
    assert ("other", "medium") in slices
    assert ("momentum", "medium") in slices
    assert slices[("other", "short")]["signals"] == 1


def test_apply_price_window_labels_uses_future_market_observation():
    row = _row("alpha", signal_id=1, is_correct=None)
    row.created_at = "2026-04-03T12:00:00+00:00"
    row.time_window = "intraday"
    row.market_id = "market-1"
    row.market_price = 0.4
    observations = {
        "market-1": [
            PriceObservation("market-1", "2026-04-03T13:00:00+00:00", 0.45, "signal"),
            PriceObservation("market-1", "2026-04-03T18:00:00+00:00", 0.48, "execution_check"),
        ]
    }
    meta = {
        "alpha": {
            "target_hold_min_days": 1 / 24,
            "target_hold_max_days": 1.0,
        }
    }

    apply_price_window_labels([row], observations_by_market=observations, meta=meta)

    assert row.is_labeled is True
    assert row.is_correct is True
    assert row.label_source == "price_window"
    assert row.future_yes_price == 0.48
    assert row.price_move_pp == 8.0


def test_load_price_observations_prefers_market_observations_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "bench.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE market_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_slug TEXT,
            market_id TEXT NOT NULL,
            market_slug TEXT,
            market_title TEXT,
            yes_price REAL,
            best_bid REAL,
            best_ask REAL,
            spread REAL,
            liquidity REAL,
            volume REAL,
            volume_24hr REAL,
            close_time TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            strategy TEXT,
            market_id TEXT,
            market_title TEXT,
            outcome TEXT,
            market_price REAL,
            p_hat REAL,
            ev_pp REAL,
            confidence TEXT,
            closes TEXT,
            url TEXT,
            rationale TEXT,
            time_window TEXT,
            edge_type TEXT,
            decision_status TEXT,
            created_at TEXT
        );
        CREATE TABLE signal_execution_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            strategy TEXT,
            market_id TEXT,
            market_title TEXT,
            outcome TEXT,
            quote_price REAL,
            created_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO market_observations (run_id, market_id, yes_price, created_at) VALUES (?, ?, ?, ?)",
        ("run-1", "m1", 0.61, "2026-04-03T13:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO signals (run_id, strategy, market_id, market_title, outcome, market_price, p_hat, ev_pp, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("run-1", "alpha", "m1", "Market", "YES", 0.2, 0.3, 10.0, "2026-04-03T13:00:00+00:00"),
    )
    conn.commit()

    observations = load_price_observations(conn)

    assert observations["m1"][0].yes_price == 0.61
    assert observations["m1"][0].source == "market_observation"


def test_market_observations_drive_price_window_labeling(tmp_path):
    conn = sqlite3.connect(tmp_path / "bench.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE market_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_slug TEXT,
            market_id TEXT NOT NULL,
            market_slug TEXT,
            market_title TEXT,
            yes_price REAL,
            best_bid REAL,
            best_ask REAL,
            spread REAL,
            liquidity REAL,
            volume REAL,
            volume_24hr REAL,
            close_time TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO market_observations (run_id, market_id, yes_price, created_at) VALUES (?, ?, ?, ?)",
        ("run-1", "m1", 0.57, "2026-04-03T18:00:00+00:00"),
    )
    conn.commit()

    row = _row("alpha", signal_id=1, is_correct=None)
    row.market_id = "m1"
    row.created_at = "2026-04-03T12:00:00+00:00"
    row.time_window = "intraday"
    row.market_price = 0.40

    observations = load_price_observations(conn)
    apply_price_window_labels(
        [row],
        observations_by_market=observations,
        meta={"alpha": {"target_hold_min_days": 1 / 24, "target_hold_max_days": 1.0}},
    )

    assert row.is_labeled is True
    assert row.label_source == "price_window"
    assert row.future_yes_price == 0.57
    assert row.price_move_pp == 17.0
    assert row.is_correct is True

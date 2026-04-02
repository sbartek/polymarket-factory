from factory.execution import build_market_index, snapshot_for_signal
from factory.models import Signal


class DummyStrategy:
    min_ev_pp = 10.0


def _sample_event() -> dict:
    return {
        "slug": "event-slug",
        "liquidity": 800.0,
        "markets": [
            {
                "id": "123",
                "slug": "sub-slug",
                "question": "Example market",
                "bestBid": 0.4,
                "bestAsk": 0.42,
                "spread": 0.02,
                "orderMinSize": 1.0,
                "volume": 20000.0,
                "closed": False,
            }
        ],
    }


def test_snapshot_for_submarket_signal_uses_market_fields():
    signal = Signal(
        strategy="spread_arb",
        market_id="event-slug:123",
        market_title="Example market",
        outcome="YES",
        market_price=0.41,
        p_hat=0.55,
        ev_pp=14.0,
        confidence="high",
        closes="2026-06-01",
        url="https://example.com",
    )
    snapshot = snapshot_for_signal(signal, DummyStrategy(), build_market_index([_sample_event()]))
    assert snapshot.best_bid == 0.4
    assert snapshot.best_ask == 0.42
    assert snapshot.quote_price == 0.41
    assert snapshot.fill_price_10 >= snapshot.best_ask
    assert snapshot.fill_price_250 >= snapshot.fill_price_10
    assert snapshot.max_size_positive_ev in {0.0, 10.0, 25.0, 50.0, 100.0, 250.0}


def test_snapshot_falls_back_when_market_lookup_is_missing():
    signal = Signal(
        strategy="ev_news",
        market_id="missing-slug",
        market_title="Unknown market",
        outcome="YES",
        market_price=0.35,
        p_hat=0.5,
        ev_pp=15.0,
        confidence="medium",
        closes="2026-06-01",
        url="https://example.com",
    )
    snapshot = snapshot_for_signal(signal, DummyStrategy(), {})
    assert snapshot.source_confidence == "very_low"
    assert snapshot.fill_price_250 >= snapshot.fill_price_10
    assert snapshot.ev_after_slippage_250_pp <= snapshot.ev_after_slippage_10_pp


def test_snapshot_for_no_signal_uses_no_side_of_book():
    signal = Signal(
        strategy="correlated_laggard",
        market_id="event-slug:123",
        market_title="Example market",
        outcome="NO",
        market_price=0.59,
        p_hat=0.68,
        ev_pp=9.0,
        confidence="medium",
        closes="2026-06-01",
        url="https://example.com",
    )
    snapshot = snapshot_for_signal(signal, DummyStrategy(), build_market_index([_sample_event()]))
    assert snapshot.best_bid == 0.58
    assert snapshot.best_ask == 0.6
    assert snapshot.quote_price == 0.59
    assert snapshot.fill_price_10 >= snapshot.best_ask
    assert 0 < snapshot.ev_after_slippage_10_pp < signal.ev_pp

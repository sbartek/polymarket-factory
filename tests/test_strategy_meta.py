from factory.strategy_meta import strategy_metadata


def test_alert_only_promotion_metadata_is_exposed_for_candidates():
    meta = strategy_metadata()

    # correlated_laggard and esport48 promoted to paper trading
    correlated_laggard = meta["correlated_laggard"]
    assert correlated_laggard["alert_only"] is False
    assert correlated_laggard["trading_enabled"] is True

    esport48 = meta["esport48"]
    assert esport48["alert_only"] is False
    assert esport48["trading_enabled"] is True

    # price_move_fade is alert-only and promotable
    price_move_fade = meta["price_move_fade"]
    assert price_move_fade["alert_only"] is True
    assert price_move_fade["trading_enabled"] is False
    assert price_move_fade["promotable"] is True
    assert price_move_fade["promotion_candidate"] is True

    celebrity_tabloid = meta["celebrity_tabloid"]
    assert celebrity_tabloid["alert_only"] is False
    assert celebrity_tabloid["trading_enabled"] is True
    assert celebrity_tabloid["promotable"] is False
    assert celebrity_tabloid["live_ready"] is False


def test_existing_paper_trading_strategies_remain_trading_enabled():
    meta = strategy_metadata()

    # spread_arb was killed 2026-04-07 (-94% ROI, 79 trades)
    assert meta["spread_arb"]["trading_enabled"] is False
    assert meta["stale_market"]["trading_enabled"] is True

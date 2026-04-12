from factory.strategy_meta import strategy_metadata


def test_alert_only_promotion_metadata_is_exposed_for_candidates():
    meta = strategy_metadata()

    # correlated_laggard demoted back to alert-only (broken matching, -$6.93)
    correlated_laggard = meta["correlated_laggard"]
    assert correlated_laggard["alert_only"] is True
    assert correlated_laggard["trading_enabled"] is False

    # esport48 rewritten with Pinnacle odds comparison, alert-only pending validation
    esport48 = meta["esport48"]
    assert esport48["alert_only"] is True
    assert esport48["trading_enabled"] is False

    # price_move_fade promoted to paper trading 2026-04-07
    price_move_fade = meta["price_move_fade"]
    assert price_move_fade["alert_only"] is False
    assert price_move_fade["trading_enabled"] is True

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

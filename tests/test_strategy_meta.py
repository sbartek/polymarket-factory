from factory.strategy_meta import strategy_metadata


def test_alert_only_promotion_metadata_is_exposed_for_candidates():
    meta = strategy_metadata()

    correlated_laggard = meta["correlated_laggard"]
    assert correlated_laggard["alert_only"] is True
    assert correlated_laggard["trading_enabled"] is False
    assert correlated_laggard["promotable"] is True
    assert correlated_laggard["live_ready"] is False
    assert correlated_laggard["promotion_candidate"] is True

    esport48 = meta["esport48"]
    assert esport48["alert_only"] is True
    assert esport48["trading_enabled"] is False
    assert esport48["promotable"] is True
    assert esport48["live_ready"] is False
    assert esport48["promotion_candidate"] is True

    celebrity_tabloid = meta["celebrity_tabloid"]
    assert celebrity_tabloid["alert_only"] is True
    assert celebrity_tabloid["trading_enabled"] is False
    assert celebrity_tabloid["promotable"] is True
    assert celebrity_tabloid["live_ready"] is False
    assert celebrity_tabloid["promotion_candidate"] is True


def test_existing_paper_trading_strategies_remain_trading_enabled():
    meta = strategy_metadata()

    assert meta["spread_arb"]["trading_enabled"] is True
    assert meta["stale_market"]["trading_enabled"] is True

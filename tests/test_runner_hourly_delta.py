from factory.runner import _extract_market_observations, _format_hourly_delta, format_wa_summary


def test_format_hourly_delta_shows_sign_and_coverage():
    current = {
        "net_usdc": 112.34,
        "unrealized_pnl_usdc": 7.89,
        "marked_positions": 4,
        "stale_positions": 1,
    }
    previous = {
        "net_usdc": 100.00,
        "unrealized_pnl_usdc": 2.50,
    }

    text = _format_hourly_delta(current, previous)

    assert text == "*1h delta:* +$12.34 net · unrealized +5.39 · marked 4, 1 stale"


def test_format_wa_summary_includes_hourly_delta_in_intraday_updates():
    stats = {
        "by_strategy": {},
        "by_status_group": {},
        "total_pnl": 0.0,
        "total_staked": 0.0,
        "roi": 0.0,
        "open": 0,
    }

    text = format_wa_summary(
        new_trades=[],
        closed_trades=[],
        alert_signals=[],
        closed_count=0,
        stats=stats,
        now="2026-04-03 11:00",
        skipped=[],
        hour=11,
        hourly_delta="*1h delta:* -$3.21 net · unrealized -1.10 · marked 2",
    )

    assert "*1h delta:* -$3.21 net · unrealized -1.10 · marked 2" in text


def test_extract_market_observations_emits_direct_and_prefixed_market_ids():
    rows = _extract_market_observations([
        {
            "slug": "event-a",
            "title": "Event A",
            "volume": 2500,
            "volume24hr": 400,
            "liquidity": 150,
            "endDate": "2026-04-10T00:00:00Z",
            "markets": [
                {
                    "id": 123,
                    "slug": "market-a",
                    "question": "Example market",
                    "outcomePrices": "[0.42,0.58]",
                    "bestBid": "0.40",
                    "bestAsk": "0.44",
                    "spread": "0.04",
                }
            ],
        }
    ])

    assert len(rows) == 3
    assert rows[0]["market_id"] == "event-a"
    assert rows[1]["market_id"] == "123"
    assert rows[2]["market_id"] == "event-a:123"
    assert rows[0]["yes_price"] == 0.42
    assert rows[0]["volume_24hr"] == 400.0

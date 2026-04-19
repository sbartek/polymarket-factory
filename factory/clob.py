"""Polymarket CLOB API wrapper — thin layer over py-clob-client."""
import json
import os

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon mainnet


def _client():
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    key = os.environ["POLYMARKET_WALLET_PRIVATE_KEY"]
    creds = ApiCreds(
        api_key=os.environ["POLYMARKET_API_KEY"],
        api_secret=os.environ["POLYMARKET_API_SECRET"],
        api_passphrase=os.environ["POLYMARKET_PASSPHRASE"],
    )
    funder = os.environ.get("POLYMARKET_PROXY_ADDRESS", "")
    return ClobClient(
        CLOB_HOST, key=key, chain_id=CHAIN_ID, creds=creds,
        signature_type=2, funder=funder or None,
    )


def get_clob_token_ids(market: dict) -> tuple[str | None, str | None]:
    """Returns (yes_token_id, no_token_id) from a Gamma API market dict."""
    raw = market.get("clobTokenIds")
    if not raw:
        return None, None
    try:
        ids = json.loads(raw) if isinstance(raw, str) else raw
        if len(ids) >= 2:
            return ids[0], ids[1]
        if len(ids) == 1:
            return ids[0], None
    except (ValueError, TypeError):
        pass
    return None, None


def place_market_order(token_id: str, size: float, timeout: int = 10) -> dict:
    """Buy `size` tokens at market (FOK). Returns order response dict."""
    import signal as _signal

    def _timeout_handler(signum, frame):
        raise TimeoutError(f"CLOB order timed out after {timeout}s")

    from py_clob_client.clob_types import MarketOrderArgs, OrderType
    client = _client()
    order = client.create_market_order(MarketOrderArgs(token_id=token_id, amount=size, side="BUY"))
    old = _signal.signal(_signal.SIGALRM, _timeout_handler)
    _signal.alarm(timeout)
    try:
        return client.post_order(order, OrderType.FOK)
    finally:
        _signal.alarm(0)
        _signal.signal(_signal.SIGALRM, old)


def cancel_all() -> dict:
    return _client().cancel_all()

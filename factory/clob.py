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
    return ClobClient(CLOB_HOST, key=key, chain_id=CHAIN_ID, creds=creds)


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


def place_market_order(token_id: str, size: float) -> dict:
    """Buy `size` tokens at market (FOK). Returns order response dict."""
    from py_clob_client.clob_types import OrderArgs, OrderType
    client = _client()
    order = client.create_market_order(OrderArgs(token_id=token_id, amount=size))
    return client.post_order(order, OrderType.FOK)


def cancel_all() -> dict:
    return _client().cancel_all()

#!/usr/bin/env python3
"""
Generate Polymarket CLOB API credentials from wallet private key
and append them to .env.

Usage:
    uv run python scripts/setup_clob_credentials.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

from py_clob_client_v2 import ClobClient

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

key = os.environ.get("POLYMARKET_WALLET_PRIVATE_KEY")
if not key:
    print("ERROR: POLYMARKET_WALLET_PRIVATE_KEY not set in .env")
    sys.exit(1)

print("Connecting to CLOB...")
client = ClobClient(CLOB_HOST, key=key, chain_id=CHAIN_ID)

print("Generating API credentials...")
creds = client.create_api_key()
print(f"  api_key:    {creds.api_key}")
print(f"  api_secret: {creds.api_secret}")
print(f"  passphrase: {creds.api_passphrase}")

with open(ENV_PATH, "a") as f:
    f.write(f"\nPOLYMARKET_API_KEY={creds.api_key}")
    f.write(f"\nPOLYMARKET_API_SECRET={creds.api_secret}")
    f.write(f"\nPOLYMARKET_PASSPHRASE={creds.api_passphrase}\n")

print("\nCredentials appended to .env — ready to trade!")

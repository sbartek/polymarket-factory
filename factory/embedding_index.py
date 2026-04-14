"""Embedding-based base rate index using Gemini embeddings + pgvector.

Replaces TF-IDF kNN with semantic embeddings for finding similar resolved
markets. Uses Google's text-embedding-005 (768 dims) via Vertex AI and
pgvector for efficient cosine similarity search in PostgreSQL.

Usage:
    # At backfill time (scripts/backfill_embeddings.py):
    index = EmbeddingIndex()
    index.add_markets([{"slug": "...", "title": "...", "resolved_yes": 1}])

    # At scan time (strategies/base_rate_anchor.py):
    index = EmbeddingIndex()
    result = index.query_base_rate("Will Trump announce ceasefire?", k=10)
"""
from __future__ import annotations

import os
import time

from google import genai
from google.genai import types

from .db import FactoryDB

GEMINI_MODEL = "text-embedding-005"
GEMINI_PROJECT = "pplayouts-factory"
GEMINI_LOCATION = "us-central1"
EMBEDDING_DIMS = 768
BATCH_SIZE = 100  # Gemini supports batch embedding


def _get_client():
    return genai.Client(vertexai=True, project=GEMINI_PROJECT, location=GEMINI_LOCATION)


def embed_texts(texts: list[str], client=None) -> list[list[float]]:
    """Embed a batch of texts using Gemini. Returns list of 768-dim vectors."""
    if not texts:
        return []
    client = client or _get_client()
    result = client.models.embed_content(
        model=GEMINI_MODEL,
        contents=texts,
    )
    return [emb.values for emb in result.embeddings]


def embed_one(text: str, client=None) -> list[float]:
    """Embed a single text."""
    return embed_texts([text], client)[0]


class EmbeddingIndex:
    """pgvector-backed embedding index for resolved market base rates."""

    def __init__(self):
        self.db = FactoryDB()
        self._client = None

    def _gemini(self):
        if self._client is None:
            self._client = _get_client()
        return self._client

    @property
    def size(self) -> int:
        with self.db._conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM base_rate_embeddings")
            return cur.fetchone()[0]

    def add_markets(self, markets: list[dict]) -> int:
        """Add resolved markets with embeddings. Skips duplicates by slug.
        Each dict: slug, title, resolved_yes, end_date?, volume?
        Returns count of new entries added.
        """
        if not markets:
            return 0

        # Filter out already-indexed slugs
        slugs = [m["slug"] for m in markets if m.get("slug") and m.get("title")]
        if not slugs:
            return 0

        with self.db._conn() as (conn, cur):
            cur.execute(
                "SELECT slug FROM base_rate_embeddings WHERE slug = ANY(%s)",
                (slugs,),
            )
            existing = {row[0] for row in cur.fetchall()}

        new_markets = [m for m in markets if m["slug"] not in existing and m.get("title")]
        if not new_markets:
            return 0

        # Embed in batches
        added = 0
        for i in range(0, len(new_markets), BATCH_SIZE):
            batch = new_markets[i:i + BATCH_SIZE]
            titles = [m["title"] for m in batch]

            try:
                embeddings = embed_texts(titles, self._gemini())
            except Exception as e:
                print(f"  [embedding_index] embed failed at batch {i}: {e}")
                continue

            with self.db._conn() as (conn, cur):
                for m, emb in zip(batch, embeddings):
                    try:
                        cur.execute(
                            """
                            INSERT INTO base_rate_embeddings (slug, title, resolved_yes, end_date, volume, embedding)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (slug) DO NOTHING
                            """,
                            (
                                m["slug"],
                                m["title"],
                                int(m.get("resolved_yes", 0)),
                                m.get("end_date", ""),
                                float(m.get("volume", 0)),
                                emb,
                            ),
                        )
                        added += 1
                    except Exception as e:
                        print(f"  [embedding_index] insert failed for {m['slug']}: {e}")

            if i + BATCH_SIZE < len(new_markets):
                time.sleep(0.5)  # rate limit courtesy

        return added

    def query_base_rate(self, title: str, k: int = 10) -> dict:
        """Find k nearest resolved markets by embedding similarity.

        Returns dict with:
            base_rate: float (0.0-1.0)
            n_neighbors: int
            neighbors: list of dicts with slug, title, resolved_yes, similarity
        """
        if self.size < 50:
            return {"base_rate": 0.5, "n_neighbors": 0, "neighbors": []}

        try:
            query_emb = embed_one(title, self._gemini())
        except Exception as e:
            print(f"  [embedding_index] query embed failed: {e}")
            return {"base_rate": 0.5, "n_neighbors": 0, "neighbors": []}

        with self.db._conn() as (conn, cur):
            cur.execute(
                """
                SELECT slug, title, resolved_yes,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM base_rate_embeddings
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_emb, query_emb, k),
            )
            neighbors = []
            for row in cur.fetchall():
                sim = float(row[2 + 1])  # similarity column
                if sim < 0.3:  # minimum similarity threshold
                    continue
                neighbors.append({
                    "slug": row[0],
                    "title": row[1],
                    "resolved_yes": int(row[2]),
                    "similarity": round(sim, 4),
                })

        if not neighbors:
            return {"base_rate": 0.5, "n_neighbors": 0, "neighbors": []}

        base_rate = sum(n["resolved_yes"] for n in neighbors) / len(neighbors)
        return {
            "base_rate": round(base_rate, 4),
            "n_neighbors": len(neighbors),
            "neighbors": neighbors,
        }

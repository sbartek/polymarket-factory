"""Base rate index: TF-IDF + cosine similarity kNN over resolved Polymarket markets.

Stores resolved market titles with their outcomes (YES=1, NO=0).
Given a new market title, finds k nearest neighbors and returns
the average resolution rate as the estimated base rate.

Persistence: pickle file at data/base_rate_index.pkl
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DEFAULT_INDEX_PATH = Path(__file__).resolve().parents[1] / "data" / "base_rate_index.pkl"


@dataclass
class IndexEntry:
    slug: str
    title: str
    resolved_yes: int  # 1 if resolved YES, 0 if NO
    end_date: str = ""
    volume: float = 0.0


@dataclass
class BaseRateIndex:
    entries: list[IndexEntry] = field(default_factory=list)
    _slug_set: set[str] = field(default_factory=set, repr=False)
    _vectorizer: TfidfVectorizer | None = field(default=None, repr=False)
    _matrix: np.ndarray | None = field(default=None, repr=False)

    def add_markets(self, markets: list[dict]) -> int:
        """Add resolved markets. Each dict: slug, title, resolved_yes, end_date?, volume?.
        Returns count of new entries added (deduped by slug)."""
        added = 0
        for m in markets:
            slug = m.get("slug", "")
            if not slug or slug in self._slug_set:
                continue
            self._slug_set.add(slug)
            self.entries.append(IndexEntry(
                slug=slug,
                title=m["title"],
                resolved_yes=int(m.get("resolved_yes", 0)),
                end_date=m.get("end_date", ""),
                volume=float(m.get("volume", 0)),
            ))
            added += 1
        if added:
            self._rebuild_matrix()
        return added

    def _rebuild_matrix(self) -> None:
        if not self.entries:
            self._vectorizer = None
            self._matrix = None
            return
        self._vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            stop_words="english",
            lowercase=True,
        )
        titles = [e.title for e in self.entries]
        self._matrix = self._vectorizer.fit_transform(titles)

    def query_base_rate(self, title: str, k: int = 10) -> dict:
        """Find k nearest resolved markets and return estimated base rate.

        Returns dict with:
            base_rate: float (0.0-1.0) — average YES resolution rate of neighbors
            n_neighbors: int — actual number of neighbors found
            neighbors: list of dicts with slug, title, resolved_yes, similarity
        """
        if not self.entries or self._vectorizer is None or self._matrix is None:
            return {"base_rate": 0.5, "n_neighbors": 0, "neighbors": []}

        query_vec = self._vectorizer.transform([title])
        sims = cosine_similarity(query_vec, self._matrix).flatten()

        # Get top-k indices (exclude exact 1.0 similarity = same market)
        top_indices = np.argsort(sims)[::-1]
        neighbors = []
        for idx in top_indices:
            if len(neighbors) >= k:
                break
            sim = float(sims[idx])
            if sim >= 1.0:
                continue  # skip exact match
            if sim < 0.01:
                break  # too dissimilar
            entry = self.entries[idx]
            neighbors.append({
                "slug": entry.slug,
                "title": entry.title,
                "resolved_yes": entry.resolved_yes,
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

    def save(self, path: Path | None = None) -> None:
        path = path or DEFAULT_INDEX_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": [(e.slug, e.title, e.resolved_yes, e.end_date, e.volume) for e in self.entries],
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    @classmethod
    def load(cls, path: Path | None = None) -> BaseRateIndex:
        path = path or DEFAULT_INDEX_PATH
        if not path.exists():
            return cls()
        with open(path, "rb") as f:
            data = pickle.load(f)
        idx = cls()
        for slug, title, resolved_yes, end_date, volume in data["entries"]:
            idx._slug_set.add(slug)
            idx.entries.append(IndexEntry(slug, title, resolved_yes, end_date, volume))
        idx._rebuild_matrix()
        return idx

    @property
    def size(self) -> int:
        return len(self.entries)

"""Glicko-2 rating system for CS2 teams, powered by HLTV match history.

Usage:
    # Fetch recent results and update ratings
    python -m factory.esport_ratings --fetch --days 90

    # Show current top ratings
    python -m factory.esport_ratings --top 20

    # Get win probability for a matchup
    python -m factory.esport_ratings --matchup "FURIA" "MOUZ"
"""
from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime

import glicko2

from .db import FactoryDB

# Glicko-2 defaults
DEFAULT_RATING = 1500.0
DEFAULT_RD = 350.0
DEFAULT_VOL = 0.06
# RD above this = too uncertain to trade on
MAX_TRADEABLE_RD = 200.0


def _expected_score(r1: float, rd1: float, r2: float, rd2: float) -> float:
    """Glicko-2 expected score (win probability) for player 1."""
    g = 1.0 / math.sqrt(1.0 + 3.0 * rd2**2 / math.pi**2)
    return 1.0 / (1.0 + 10.0 ** (-g * (r1 - r2) / 400.0))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _ensure_tables(db: FactoryDB):
    """Create esport rating tables if they don't exist."""
    with db._conn() as (conn, cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS esport_matches (
                id TEXT PRIMARY KEY,
                team1 TEXT NOT NULL,
                team2 TEXT NOT NULL,
                score1 INTEGER NOT NULL,
                score2 INTEGER NOT NULL,
                event TEXT,
                game TEXT NOT NULL DEFAULT 'cs2',
                match_date TEXT,
                fetched_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS esport_ratings (
                team TEXT NOT NULL,
                game TEXT NOT NULL DEFAULT 'cs2',
                rating REAL NOT NULL DEFAULT 1500.0,
                rd REAL NOT NULL DEFAULT 350.0,
                vol REAL NOT NULL DEFAULT 0.06,
                matches_played INTEGER NOT NULL DEFAULT 0,
                last_match_date TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team, game)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_esport_matches_game ON esport_matches(game)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_esport_matches_date ON esport_matches(match_date)")
        conn.commit()


def _store_matches(db: FactoryDB, matches: list[dict], game: str = "cs2"):
    """Store match results, skipping duplicates by match ID."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with db._conn() as (conn, cur):
        inserted = 0
        for m in matches:
            try:
                cur.execute("""
                    INSERT INTO esport_matches (id, team1, team2, score1, score2, event, game, match_date, fetched_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (
                    m["id"], m["team1"], m["team2"],
                    int(m["score1"]), int(m["score2"]),
                    m.get("event", ""), game,
                    m.get("match_date", now), now,
                ))
                inserted += cur.rowcount
            except Exception as e:
                print(f"  [esport_ratings] skip match {m.get('id')}: {e}")
        conn.commit()
    return inserted


def _load_all_matches(db: FactoryDB, game: str = "cs2") -> list[dict]:
    """Load all matches ordered chronologically."""
    with db._conn() as (conn, cur):
        cur.execute("""
            SELECT id, team1, team2, score1, score2, event, match_date
            FROM esport_matches
            WHERE game = %s
            ORDER BY match_date ASC, id ASC
        """, (game,))
        return [dict(r) for r in cur.fetchall()]


def _save_ratings(db: FactoryDB, ratings: dict[str, dict], game: str = "cs2"):
    """Persist all ratings to DB."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with db._conn() as (conn, cur):
        for team, r in ratings.items():
            cur.execute("""
                INSERT INTO esport_ratings (team, game, rating, rd, vol, matches_played, last_match_date, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (team, game) DO UPDATE SET
                    rating = EXCLUDED.rating,
                    rd = EXCLUDED.rd,
                    vol = EXCLUDED.vol,
                    matches_played = EXCLUDED.matches_played,
                    last_match_date = EXCLUDED.last_match_date,
                    updated_at = EXCLUDED.updated_at
            """, (
                team, game,
                round(r["rating"], 2), round(r["rd"], 2), round(r["vol"], 6),
                r["matches"], r.get("last_date", ""), now,
            ))
        conn.commit()


def load_ratings(db: FactoryDB, game: str = "cs2") -> dict[str, dict]:
    """Load all ratings from DB."""
    with db._conn() as (conn, cur):
        cur.execute("""
            SELECT team, rating, rd, vol, matches_played, last_match_date
            FROM esport_ratings WHERE game = %s
        """, (game,))
        return {
            r["team"]: {
                "rating": float(r["rating"]),
                "rd": float(r["rd"]),
                "vol": float(r["vol"]),
                "matches": int(r["matches_played"]),
                "last_date": r["last_match_date"],
            }
            for r in cur.fetchall()
        }


# ---------------------------------------------------------------------------
# HLTV fetch
# ---------------------------------------------------------------------------

async def _fetch_hltv_results(days: int = 90, max_results: int = 200) -> list[dict]:
    """Fetch CS2 match results from HLTV."""
    from hltv_async_api import Hltv

    hltv = Hltv()
    try:
        results = await hltv.get_results(days=days, max=max_results)
        if not results:
            return []
        return [
            {
                "id": str(r["id"]),
                "team1": r["team1"],
                "team2": r["team2"],
                "score1": str(r["score1"]),
                "score2": str(r["score2"]),
                "event": r.get("event", ""),
                "match_date": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            for r in results
            if r.get("team1") and r.get("team2")
        ]
    finally:
        await hltv.close()


def fetch_results(days: int = 90, max_results: int = 200) -> list[dict]:
    """Synchronous wrapper for HLTV fetch."""
    return asyncio.run(_fetch_hltv_results(days, max_results))


# ---------------------------------------------------------------------------
# Glicko-2 rating computation
# ---------------------------------------------------------------------------

def rebuild_ratings(db: FactoryDB, game: str = "cs2") -> dict[str, dict]:
    """Rebuild all ratings from scratch using stored match history."""
    matches = _load_all_matches(db, game)
    if not matches:
        print("  [esport_ratings] no matches to process")
        return {}

    players: dict[str, glicko2.Player] = {}
    match_counts: dict[str, int] = {}
    last_dates: dict[str, str] = {}

    def _get(team: str) -> glicko2.Player:
        if team not in players:
            players[team] = glicko2.Player()
            match_counts[team] = 0
        return players[team]

    for m in matches:
        t1, t2 = m["team1"], m["team2"]
        s1, s2 = int(m["score1"]), int(m["score2"])
        date = m.get("match_date", "")

        if s1 == s2:
            continue  # skip draws (shouldn't happen in CS2 but be safe)

        p1 = _get(t1)
        p2 = _get(t2)

        # Outcome: 1 = win, 0 = loss
        outcome1 = 1.0 if s1 > s2 else 0.0
        outcome2 = 1.0 - outcome1

        # Update both players
        r1, rd1 = p1.rating, p1.rd
        r2, rd2 = p2.rating, p2.rd
        p1.update_player([r2], [rd2], [outcome1])
        p2.update_player([r1], [rd1], [outcome2])

        match_counts[t1] = match_counts.get(t1, 0) + 1
        match_counts[t2] = match_counts.get(t2, 0) + 1
        if date:
            last_dates[t1] = date
            last_dates[t2] = date

    ratings = {}
    for team, p in players.items():
        ratings[team] = {
            "rating": p.rating,
            "rd": p.rd,
            "vol": p.vol,
            "matches": match_counts.get(team, 0),
            "last_date": last_dates.get(team, ""),
        }

    _save_ratings(db, ratings, game)
    print(f"  [esport_ratings] rebuilt ratings for {len(ratings)} teams from {len(matches)} matches")
    return ratings


# ---------------------------------------------------------------------------
# Public API for strategy
# ---------------------------------------------------------------------------

def get_win_probability(db: FactoryDB, team1: str, team2: str, game: str = "cs2") -> dict | None:
    """Get expected win probability for team1 vs team2.

    Returns dict with p1_win, p2_win, confidence, or None if teams unknown.
    """
    ratings = load_ratings(db, game)

    r1 = _fuzzy_lookup(team1, ratings)
    r2 = _fuzzy_lookup(team2, ratings)

    if not r1 or not r2:
        return None

    p1_win = _expected_score(r1["rating"], r1["rd"], r2["rating"], r2["rd"])

    # Confidence based on RD
    avg_rd = (r1["rd"] + r2["rd"]) / 2
    if avg_rd > MAX_TRADEABLE_RD:
        confidence = "low"
    elif avg_rd > 120:
        confidence = "medium"
    else:
        confidence = "high"

    return {
        "p1_win": round(p1_win, 4),
        "p2_win": round(1 - p1_win, 4),
        "team1_rating": round(r1["rating"], 1),
        "team1_rd": round(r1["rd"], 1),
        "team1_matches": r1["matches"],
        "team2_rating": round(r2["rating"], 1),
        "team2_rd": round(r2["rd"], 1),
        "team2_matches": r2["matches"],
        "confidence": confidence,
    }


def _normalize_team_name(name: str) -> str:
    """Normalize for fuzzy matching."""
    import re
    name = name.lower().strip()
    name = re.sub(r"\besports?\b", "", name).strip()
    name = re.sub(r"\bgaming\b", "", name).strip()
    name = re.sub(r"\bteam\b", "", name).strip()
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _fuzzy_lookup(name: str, ratings: dict[str, dict]) -> dict | None:
    """Find best matching team in ratings."""
    # Exact match
    if name in ratings:
        return ratings[name]

    # Case-insensitive
    lower_map = {k.lower(): k for k in ratings}
    if name.lower() in lower_map:
        return ratings[lower_map[name.lower()]]

    # Normalized match
    norm = _normalize_team_name(name)
    best_key = None
    best_score = 0.0
    for k in ratings:
        nk = _normalize_team_name(k)
        if nk == norm:
            return ratings[k]
        # Substring match
        if norm in nk or nk in norm:
            score = len(min(norm, nk, key=len)) / len(max(norm, nk, key=len))
            if score > best_score:
                best_score = score
                best_key = k

    if best_key and best_score >= 0.5:
        return ratings[best_key]
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Esport Glicko-2 ratings")
    parser.add_argument("--fetch", action="store_true", help="Fetch HLTV results")
    parser.add_argument("--days", type=int, default=90, help="Days of history to fetch")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild ratings from stored matches")
    parser.add_argument("--top", type=int, default=0, help="Show top N teams")
    parser.add_argument("--matchup", nargs=2, metavar=("TEAM1", "TEAM2"), help="Get win probability")
    args = parser.parse_args()

    db = FactoryDB()
    _ensure_tables(db)

    if args.fetch:
        print(f"Fetching HLTV results ({args.days} days)...")
        results = fetch_results(days=args.days)
        print(f"Got {len(results)} results from HLTV")
        inserted = _store_matches(db, results)
        print(f"Inserted {inserted} new matches")

    if args.rebuild or args.fetch:
        print("Rebuilding ratings...")
        ratings = rebuild_ratings(db)
    else:
        ratings = load_ratings(db)

    if args.top:
        sorted_teams = sorted(ratings.items(), key=lambda x: x[1]["rating"], reverse=True)
        print(f"\nTop {args.top} CS2 teams:")
        for i, (team, r) in enumerate(sorted_teams[:args.top], 1):
            print(f"  {i:2d}. {team:25s} | {r['rating']:7.1f} +/- {r['rd']:5.1f} | {r['matches']} matches")

    if args.matchup:
        t1, t2 = args.matchup
        result = get_win_probability(db, t1, t2)
        if result:
            print(f"\n{t1} vs {t2}:")
            print(f"  {t1}: {result['p1_win']*100:.1f}% (rating {result['team1_rating']}, RD {result['team1_rd']})")
            print(f"  {t2}: {result['p2_win']*100:.1f}% (rating {result['team2_rating']}, RD {result['team2_rd']})")
            print(f"  Confidence: {result['confidence']}")
        else:
            print(f"  Could not find ratings for both teams")

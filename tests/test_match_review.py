"""Offline tests for Phase 5: match history sync + post-game analysis.

Fake LCU client + fake Ollama engine + in-memory SQLite. No network.

Run: python -m pytest tests/test_match_review.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.ai.match_review import MatchReviewAnalyzer
from sylqon.db import matches as match_store
from sylqon.db.schema import Base, Champion, MatchHistory
from sylqon.lcu.history import recent_games

GAMES = [
    {"gameId": 1, "queueId": 420, "gameCreation": 2000, "gameDuration": 1800,
     "participants": [{"championId": 222, "timeline": {"lane": "BOTTOM", "role": "DUO_CARRY"},
                       "stats": {"win": True, "kills": 10, "deaths": 2, "assists": 8,
                                 "goldEarned": 15000, "totalDamageDealtToChampions": 30000,
                                 "totalDamageTaken": 12000, "visionScore": 20,
                                 "totalMinionsKilled": 200, "neutralMinionsKilled": 10,
                                 "firstBloodKill": True, "largestMultiKill": 3}}]},
    {"gameId": 2, "queueId": 420, "gameCreation": 1000, "gameDuration": 1500,
     "participants": [{"championId": 103, "timeline": {"lane": "MIDDLE", "role": "SOLO"},
                       "stats": {"win": False, "kills": 3, "deaths": 6, "assists": 4,
                                 "goldEarned": 10000, "totalDamageDealtToChampions": 20000,
                                 "totalDamageTaken": 18000, "visionScore": 12,
                                 "totalMinionsKilled": 150, "neutralMinionsKilled": 0}}]},
    {"gameId": 3, "queueId": 450, "gameCreation": 500, "gameDuration": 1200,  # ARAM -> excluded
     "participants": [{"championId": 222, "timeline": {}, "stats": {"win": True}}]},
]


class FakeClient:
    def is_alive(self):
        return True

    def get_json(self, path):
        return {"games": {"games": GAMES}}


class FakeEngine:
    def __init__(self, available=True, response=None):
        self._a, self._r = available, response

    def available(self):
        return self._a

    def evaluate(self, prompt, options=None):
        return self._r


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True, expire_on_commit=False)()
    s.add(Champion(name="Jinx", riot_key=222, slug="Jinx", roles=["bottom"]))
    s.add(Champion(name="Ahri", riot_key=103, slug="Ahri", roles=["middle"]))
    s.commit()
    return s


def test_recent_games_normalization():
    games = recent_games(FakeClient(), 10)
    assert [g["game_id"] for g in games] == ["1", "2"]   # newest first; ARAM excluded
    g = games[0]
    assert g["role"] == "bottom" and g["result"] == "Win"
    assert g["stats"]["cs"] == 210
    assert g["stats"]["cs_per_min"] == 7.0
    assert {"time": 0, "event": "First Blood"} in g["timeline"]
    assert games[1]["role"] == "middle" and games[1]["result"] == "Loss"


def test_sync_and_serialize_and_dedupe():
    session = _session()
    n = match_store.sync_recent_matches(session, FakeClient(), 10)
    session.commit()
    assert n == 2
    assert session.query(MatchHistory).count() == 2

    m = session.query(MatchHistory).filter_by(game_id="1").one()
    ser = match_store.serialize_match(session, m)
    assert ser["champion"] == "Jinx"
    assert ser["result"] == "Win"
    assert ser["has_analysis"] is False
    assert ser["duration"] == 1800

    # Re-sync: no duplicates.
    match_store.sync_recent_matches(session, FakeClient(), 10)
    session.commit()
    assert session.query(MatchHistory).count() == 2


def test_analyzer_clips_and_degrades():
    md = {"champion": "Jinx", "role": "bottom", "result": "Win", "duration": 1800,
          "kda": {"kills": 10, "deaths": 2, "assists": 8},
          "stats": {"gold": 15000, "total_damage": 30000, "damage_taken": 12000,
                    "vision_score": 20, "cs": 210, "cs_per_min": 7.0},
          "timeline": [{"time": 330, "event": "First Blood"}]}

    ok = MatchReviewAnalyzer(FakeEngine(response={
        "summary": "Erős játék.", "strengths": ["a", "b", "c", "d"],
        "weaknesses": ["x"], "tips": ["t1", "t2"]})).analyze_match(md)
    assert ok["summary"] == "Erős játék."
    assert ok["strengths"] == ["a", "b", "c"]   # clipped to 3
    assert ok["weaknesses"] == ["x"]

    # Ollama offline -> None (API degrades gracefully).
    assert MatchReviewAnalyzer(FakeEngine(available=False)).analyze_match(md) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))

"""Offline tests for the auto post-game review (event-driven off the LCU
end-of-game stats block).

Fake LCU client + fake Ollama engine + shared in-memory SQLite. No network.
``_run_post_game_review`` is exercised on a PipelineRunner built via __new__ so
we skip the heavy real __init__ (catalog/cache bootstrap).

Run: python -m pytest tests/test_post_game.py -q
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sylqon.db.schema import Base, Champion, MatchAnalysis
from sylqon.runtime import AppState, PipelineRunner

GAMES = [
    {"gameId": 7, "queueId": 420, "gameCreation": 2000, "gameDuration": 1800,
     "participants": [{"championId": 222, "timeline": {"lane": "BOTTOM", "role": "DUO_CARRY"},
                       "stats": {"win": True, "kills": 10, "deaths": 2, "assists": 8,
                                 "goldEarned": 15000, "totalDamageDealtToChampions": 30000,
                                 "totalDamageTaken": 12000, "visionScore": 20,
                                 "totalMinionsKilled": 200, "neutralMinionsKilled": 10}}]},
]
REVIEW = {"summary": "Erős játék.", "strengths": ["a", "b"],
          "weaknesses": ["x"], "tips": ["t1", "t2"]}


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


@pytest.fixture()
def db(monkeypatch):
    """A shared in-memory DB wired into ``get_session`` (fresh session per call,
    same underlying database via StaticPool)."""
    engine = create_engine("sqlite://", future=True,
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    seed = Sess()
    seed.add(Champion(name="Jinx", riot_key=222, slug="Jinx", roles=["bottom"]))
    seed.commit()
    seed.close()
    monkeypatch.setattr("sylqon.db.session.get_session", lambda: Sess())
    return Sess


def make_runner(engine):
    r = PipelineRunner.__new__(PipelineRunner)
    r.client = FakeClient()
    r.engine = engine
    r._review_lock = threading.Lock()
    r._last_reviewed_game = None
    r.state = AppState()
    return r


def test_review_publishes_match_and_analysis(db):
    r = make_runner(FakeEngine(response=REVIEW))
    r._run_post_game_review()

    pg = r.state.snapshot()["post_game"]
    assert pg["active"] is True
    assert pg["pending"] is False
    assert pg["match"]["champion"] == "Jinx"
    assert pg["match"]["result"] == "Win"
    assert pg["analysis"]["summary"] == "Erős játék."
    assert r._last_reviewed_game == "7"
    # The analysis was persisted so the API serves it from cache afterwards.
    assert db().query(MatchAnalysis).count() == 1


def test_review_is_deduped_per_game(db):
    r = make_runner(FakeEngine(response=REVIEW))
    r._run_post_game_review()
    # Simulate a second eog push for the SAME game; it must not re-review.
    r.state.set("post_game", {"active": False})
    r._run_post_game_review()
    assert r.state.snapshot()["post_game"] == {"active": False}
    assert db().query(MatchAnalysis).count() == 1


def test_review_degrades_when_ollama_offline(db):
    r = make_runner(FakeEngine(available=False))
    r._run_post_game_review()
    pg = r.state.snapshot()["post_game"]
    # Match still surfaces; analysis is absent and the spinner is cleared.
    assert pg["active"] is True
    assert pg["analysis"] is None
    assert pg["pending"] is False
    assert db().query(MatchAnalysis).count() == 0


# --------------------------------------------------------------- _on_eog
def _eog_runner():
    r = PipelineRunner.__new__(PipelineRunner)
    r.client = FakeClient()
    fired = threading.Event()
    r._run_post_game_review = fired.set  # type: ignore[method-assign]
    return r, fired


def test_on_eog_triggers_review():
    r, fired = _eog_runner()
    r._on_eog({"gameId": 7}, "Update")
    assert fired.wait(timeout=2.0)


def test_on_eog_ignores_delete_and_no_client():
    r, fired = _eog_runner()
    r._on_eog({"gameId": 7}, "Delete")
    assert not fired.wait(timeout=0.2)

    r.client = None
    r._on_eog({"gameId": 7}, "Update")
    assert not fired.wait(timeout=0.2)

"""Draft Gauntlet tests: pool building, the run engine and the /gym flow."""
from __future__ import annotations

import re

import pytest
from app import config, db, gym, puzzles, store
from app.models import Base, GymPuzzle
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.test_puzzles import TEAMS, _match

RUN_LEN = 3  # tests run short gauntlets; the scoring math is length-agnostic


@pytest.fixture()
def short_runs(monkeypatch):
    monkeypatch.setattr(config, "GYM_RUN_LENGTH", RUN_LEN)


def _seed(factory):
    with factory() as s:
        for n, (blue, red) in enumerate(TEAMS):
            store.insert_match_bundle(
                s, _match(f"EUN1_{n}", 1000 + n, blue, red, blue_win=(n % 2 == 0)),
                {"info": {}}, region="europe")
        assert puzzles.build_pool_batch(s, target=10) == len(TEAMS)


# -- pool -----------------------------------------------------------------------
def test_pool_builds_once_per_match(factory):
    _seed(factory)
    with factory() as s:
        assert puzzles.build_pool_batch(s, target=10) == 0  # all matches used
        ids = list(s.execute(select(GymPuzzle.id)).scalars())
        assert len(ids) == len(TEAMS)
        payload = puzzles.get_pool_puzzle(s, ids[0])
        assert len(payload["candidates"]) == puzzles.CANDIDATE_COUNT
        assert puzzles.get_pool_puzzle(s, 999999) is None
        drawn = puzzles.draw_pool_ids(s, 3)
        assert len(drawn) == 3 and len(set(drawn)) == 3


# -- run engine --------------------------------------------------------------------
def test_run_scores_and_finishes(factory, short_runs):
    _seed(factory)
    with factory() as s:
        run = gym.start_run(s)
        assert len(run.puzzle_ids) == RUN_LEN and run.score == 0
        total = 0
        for turn in range(RUN_LEN):
            result = gym.answer(s, run, 0)
            assert result["points"] == gym.POINTS[result["tier"]]
            total += result["points"]
            assert result["done"] == (turn == RUN_LEN - 1)
        assert run.score == total and run.finished_at is not None
        with pytest.raises(gym.GymError):
            gym.answer(s, run, 0)  # replay cannot double-score
        assert len(gym.emoji_summary(run)) == RUN_LEN


def test_run_guards(factory, short_runs):
    with factory() as s:
        with pytest.raises(gym.GymError):
            gym.start_run(s)  # empty pool
    _seed(factory)
    with factory() as s:
        run = gym.start_run(s)
        with pytest.raises(gym.GymError):
            gym.answer(s, run, 99)  # out-of-range pick
        with pytest.raises(gym.GymError):
            gym.answer(s, run, "0")  # type-confused pick
        with pytest.raises(gym.GymError):
            gym.save_nickname(s, run, "Zed")  # not finished yet
        assert gym.get_run(s, "nope") is None and gym.get_run(s, None) is None


def test_nickname_rules_and_leaderboard(factory, short_runs):
    _seed(factory)
    with factory() as s:
        def finished_run():
            run = gym.start_run(s)
            for _ in range(RUN_LEN):
                gym.answer(s, run, 0)
            return run

        a, b, c = finished_run(), finished_run(), finished_run()
        assert gym.save_nickname(s, a, "  Zoé!@#{} x  ") == "Zoé x"  # sanitized
        with pytest.raises(gym.GymError):
            gym.save_nickname(s, a, "Other")  # one name per run
        with pytest.raises(gym.GymError):
            gym.save_nickname(s, b, "!")  # too short after cleaning
        gym.save_nickname(s, b, "Zoé x")  # same nickname, second run
        gym.save_nickname(s, c, "Beta")

        rows = gym.leaderboard(s)
        names = [n for n, _ in rows]
        assert names.count("Zoé x") == 1  # grouped: best per nickname
        assert set(names) == {"Zoé x", "Beta"}
        assert rows == sorted(rows, key=lambda r: (-r[1], r[0]))
        assert gym.leaderboard(s, days=1)  # finished today → in the daily window


# -- routes ---------------------------------------------------------------------
@pytest.fixture()
def client(monkeypatch, short_runs):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", factory)
    _seed(factory)
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def _run_id(fragment: str) -> str:
    return re.search(r'data-run="([0-9a-f]+)"', fragment).group(1)


def test_gym_page_renders(client):
    r = client.get("/gym")
    assert r.status_code == 200
    assert 'id="gym-start"' in r.text
    assert "Thirty points" in r.text
    assert "Today" in r.text and "All time" in r.text
    assert 'href="/gym"' in client.get("/").text  # nav links the gauntlet


def test_full_run_flow_over_http(client):
    frag = client.post("/gym/start").text
    assert 'data-state="question"' in frag
    # spoiler-free question: no tier classes, no answer flags before the pick
    assert "t-strong" not in frag and "t-solid" not in frag and "t-risky" not in frag
    assert "real pick" not in frag and "tierline" not in frag
    run_id = _run_id(frag)

    for turn in range(RUN_LEN):
        verdict = client.post("/gym/answer", json={"run": run_id, "pick": 0}).text
        assert 'data-state="verdict"' in verdict
        assert re.search(r"\+\d pts", verdict)
        assert "the real player" in verdict.lower() and "locked" in verdict.lower()
        assert ("See your result" in verdict) == (turn == RUN_LEN - 1)
        frag = client.post("/gym/view", json={"run": run_id}).text
    assert 'data-state="final"' in frag
    assert f"/ {RUN_LEN * 3}" in frag  # max score shown
    assert 'id="gym-nick"' in frag

    done = client.post("/gym/finish", json={"run": run_id, "nickname": "Tesztelő"}).text
    assert "On the board as <strong>Tesztelő</strong>" in done
    assert "Tesztelő" in client.get("/gym").text  # leaderboard shows the name


def test_gym_error_fragments_are_friendly(client):
    r = client.post("/gym/answer", json={"run": "nope", "pick": 0})
    assert r.status_code == 200 and "start a new one" in r.text
    frag = client.post("/gym/start").text
    run_id = _run_id(frag)
    bad = client.post("/gym/answer", json={"run": run_id, "pick": 42}).text
    assert "pick one of the shown candidates" in bad

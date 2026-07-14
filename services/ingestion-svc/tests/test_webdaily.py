"""Route tests for the Daily Draft pages (/daily, /daily/{date})."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from app import db, puzzles, store
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.test_puzzles import TEAMS, _match

TODAY = date.today  # the routes freeze "today" as UTC; tests derive from the same clock


def _iso(days_ago: int) -> str:
    from datetime import datetime, timezone

    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", factory)

    with factory() as s:
        for n, (blue, red) in enumerate(TEAMS):
            store.insert_match_bundle(
                s, _match(f"EUN1_{n}", 1000 + n, blue, red, blue_win=(n % 2 == 0)),
                {"info": {}}, region="europe")

    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def _gen(days_ago: int = 0) -> str:
    day = _iso(days_ago)
    with db.open_session() as s:
        puzzles.generate_for_date(s, day)
    return day


def test_daily_empty_state(client):
    r = client.get("/daily")
    assert r.status_code == 200
    assert "No puzzle yet today" in r.text


def test_daily_renders_interactive_puzzle(client):
    _gen(0)
    r = client.get("/daily")
    assert r.status_code == 200
    assert 'data-mode="play"' in r.text
    assert r.text.count('class="cand t-') == puzzles.CANDIDATE_COUNT
    assert "Pick your answer" in r.text
    assert "The engine reads their comp" in r.text
    assert 'id="solution"' in r.text  # pre-rendered, hidden until the island solves
    assert "What actually happened" in r.text
    # anonymity: neither the match id nor any player identity may reach the page
    assert "EUN1_" not in r.text and "puuid" not in r.text.lower()


def test_daily_archive_is_pre_solved(client):
    day = _gen(1)
    r = client.get(f"/daily/{day}")
    assert r.status_code == 200
    assert 'data-mode="solved"' in r.text
    assert "solution shown" in r.text
    assert "disabled" in r.text  # candidate buttons are inert on the archive
    assert "Play today" in r.text  # CTA back to the live puzzle
    assert "the real player locked this" in r.text.lower()


def test_daily_archive_guards(client):
    _gen(0)
    today = _iso(0)
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    # today + future both bounce to /daily — pre-generated puzzles must not leak
    for d in (today, tomorrow):
        r = client.get(f"/daily/{d}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/daily"
    assert "Not a puzzle date" in client.get("/daily/not-a-date").text
    assert "Not a puzzle date" in client.get("/daily/2026-02-30").text
    assert "No puzzle for" in client.get("/daily/2001-01-01").text


def test_daily_lists_archive_links(client):
    old = _gen(2)
    _gen(0)
    r = client.get("/daily")
    assert f'href="/daily/{old}"' in r.text
    r2 = client.get(f"/daily/{old}")
    assert f'href="/daily/{old}"' not in r2.text  # a page never links to itself


def test_daily_framing_guard(client):
    _gen(0)
    forbidden = ("mmr", "elo", "skill rating", "skill score", "matchmaking rating",
                 "win prediction")
    for path in ("/daily", f"/daily/{_gen(1)}"):
        text = client.get(path).text.lower()
        for word in forbidden:
            assert word not in text, f"{word!r} leaked into {path}"
        assert "not a prediction" in text  # the honesty note ships on every puzzle page


def test_home_nav_links_daily(client):
    assert 'href="/daily"' in client.get("/").text


def test_home_hosts_todays_puzzle(client):
    _gen(0)
    r = client.get("/")
    assert r.status_code == 200
    assert 'data-mode="play"' in r.text
    assert r.text.count('class="cand t-') == puzzles.CANDIDATE_COUNT
    assert "Today's puzzle" in r.text
    assert "Download for Windows" in r.text  # the conversion CTA stays above the fold
    assert "EUN1_" not in r.text  # anonymity holds on the homepage too

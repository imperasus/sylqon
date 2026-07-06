"""Route tests for the public S3 pages (TestClient + seeded SQLite)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, store
from app.models import Base

from tests.test_pool import ME, lane_match


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
        specs = [("Jinx", "Caitlyn", True), ("Jinx", "Caitlyn", True),
                 ("Jinx", "Draven", False), ("Jinx", "Draven", False),
                 ("Caitlyn", "Draven", True), ("Caitlyn", "Draven", True),
                 ("Caitlyn", "Draven", True)]
        for i, (a, b, win) in enumerate(specs):
            m = lane_match(f"EUN1_{i}", a, b, win, a_puuid=ME if a == "Jinx" else "o1")
            store.insert_match_bundle(s, m, {"info": {"frames": []}}, region="europe")

    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def test_home_renders_form(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'action="/pool-report"' in r.text
    assert "pool coverage" in r.text.lower()


def test_pool_report_uses_stored_data(client, monkeypatch):
    # No running ingest service in tests → resolve the puuid via a stub.
    import app.main as main_mod

    class StubIngest:
        def ingest(self, game_name, tag_line):
            class R:
                puuid = ME
            return R()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/pool-report", params={"riot_id": "Me#TAG"})
    assert r.status_code == 200
    assert "BOTTOM" in r.text
    assert "Jinx" in r.text
    assert "Suggested pool" in r.text
    assert "Draven" in r.text  # uncovered threat linked


def test_pool_report_invalid_riot_id(client):
    r = client.get("/pool-report", params={"riot_id": "no-tag"})
    assert r.status_code == 200
    assert "Invalid Riot ID" in r.text


def test_champions_index_and_detail(client):
    r = client.get("/champions")
    assert r.status_code == 200
    assert "Jinx" in r.text and "Caitlyn" in r.text

    r = client.get("/champion/Jinx")
    assert r.status_code == 200
    assert "Lane matchups" in r.text
    assert "Caitlyn" in r.text  # matchup row

    r = client.get("/champion/Teemo")
    assert r.status_code == 200
    assert "Not enough games" in r.text


def test_no_skill_rating_vocabulary(client):
    # ToS framing: the public pages never talk about MMR/ELO/skill ratings.
    for path in ("/", "/champions", "/champion/Jinx"):
        text = client.get(path).text.lower()
        assert "mmr" not in text and "elo" not in text

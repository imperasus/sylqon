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


def test_summoner_page_renders_profile(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t):
            return {"puuid": "P1", "gameName": g, "tagLine": t}

        def get_summoner_by_puuid(self, p):
            return {"summonerLevel": 321, "profileIconId": 7}

        def get_ranked_stats(self, p):
            return [{"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "II",
                     "leaguePoints": 44, "wins": 60, "losses": 40}]

        def get_top_mastery(self, p, count=6):
            return [{"championId": 266, "championPoints": 123456, "championLevel": 7}]

    class StubIngest:
        _riot = StubRiot()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/summoner/Faker/KR1")
    assert r.status_code == 200
    assert "Faker#KR1" in r.text
    assert "Level 321" in r.text
    assert "Gold II" in r.text  # tier title-cased, division raw
    assert "60% WR" in r.text
    assert "Aatrox" in r.text and "123,456 pts" in r.text
    low = r.text.lower()
    assert "mmr" not in low and "elo" not in low  # framing holds on the profile too


def test_summoner_page_not_found(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t):
            return None

    class StubIngest:
        _riot = StubRiot()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/summoner/Ghost/NONE")
    assert r.status_code == 200
    assert "Player not found" in r.text


def test_matches_page_lists_stored_games(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t):
            return {"puuid": ME, "gameName": g, "tagLine": t}

    class StubIngest:
        _riot = StubRiot()

        def ingest(self, g, t):
            class R:
                puuid = ME
            return R()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/summoner/Me/TAG/matches")
    assert r.status_code == 200
    assert "mrow" in r.text  # at least one match row rendered
    assert "Jinx" in r.text
    assert "Ranked Solo/Duo" in r.text


def test_match_page_shows_scoreboard(client):
    # client fixture seeded EUN1_0 (Jinx vs Caitlyn, blue win).
    r = client.get("/match/EUN1_0")
    assert r.status_code == 200
    assert "Champion" in r.text and "Items" in r.text  # scoreboard header
    assert "Victory" in r.text and "Defeat" in r.text  # both teams labelled
    assert "Jinx" in r.text


def test_match_page_not_stored(client):
    r = client.get("/match/EUN1_999")
    assert r.status_code == 200
    assert "Match not stored" in r.text


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
    # ("never player skill" in the footer is the allowed, deliberate phrasing.)
    forbidden = ("mmr", "elo", "skill rating", "skill score", "matchmaking rating")
    for path in ("/", "/champions", "/champion/Jinx"):
        text = client.get(path).text.lower()
        for word in forbidden:
            assert word not in text, f"{word!r} leaked into {path}"


def test_brand_refresh_assets(client):
    # Graphite Volt brand fidelity: fonts loaded, Signal-S mark and amber token present.
    text = client.get("/").text
    assert "Space+Grotesk" in text  # font stylesheet link
    assert 'aria-label="Sylqon"' in text  # Signal-S mark rendered in the header
    assert "--accent-2" in text  # amber secondary token in the palette

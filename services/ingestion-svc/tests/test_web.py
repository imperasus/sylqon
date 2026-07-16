"""Route tests for the public S3 pages (TestClient + seeded SQLite)."""
import pytest
from app import db, store
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
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

    from app import web
    web._champ_cache.clear()  # rendered-page cache must not leak across tests

    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def test_home_is_tool_first(client):
    # Interim homepage after the Daily Draft retirement: product hero + the
    # two live web tools; no lookup form, no puzzle.
    r = client.get("/")
    assert r.status_code == 200
    assert "Download for Windows" in r.text
    assert 'href="/draft"' in r.text and 'href="/audit"' in r.text
    assert 'action="/search"' not in r.text  # the old lookup-first home is gone
    assert "/daily" not in r.text and "/gym" not in r.text  # retired direction


def test_radical_cut_nav_and_noindex(client):
    home = client.get("/")
    header = home.text.split("</header>")[0]
    assert 'href="/champions"' not in header and "/leaderboard" not in header
    # sunset pages keep serving but leave the index (header ≙ noindex meta)
    for path in ("/champions", "/champion/Jinx", "/match/EUN1_0",
                 "/leaderboard/RANKED_SOLO_5x5", "/summoner/euw1/Ghost/NONE"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers.get("x-robots-tag") == "noindex", f"{path} missing noindex"
    for path in ("/", "/audit", "/download"):
        assert "x-robots-tag" not in client.get(path).headers, f"{path} must stay indexable"


def test_download_page(client):
    r = client.get("/download")
    assert r.status_code == 200
    assert "100% local" in r.text
    assert "imperasus.github.io/sylqon" in r.text


def test_audit_landing_form(client):
    r = client.get("/audit")
    assert r.status_code == 200
    assert 'action="/audit"' in r.text
    assert "difficulty map" in r.text


def test_pool_report_redirects_to_audit(client):
    r = client.get("/pool-report", params={"riot_id": "Me#TAG"}, follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/audit?riot_id=Me%23TAG"
    assert client.get("/pool-report", follow_redirects=False).headers["location"] == "/audit"


def test_search_redirects_to_profile(client):
    r = client.get("/search", params={"region": "na1", "riot_id": "Faker#KR1"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/summoner/na1/Faker/KR1"


def test_search_invalid_riot_id(client):
    r = client.get("/search", params={"region": "euw1", "riot_id": "no-tag"})
    assert r.status_code == 200
    assert "Invalid Riot ID" in r.text


def test_pool_report_uses_stored_data(client, monkeypatch):
    # No running ingest service in tests → resolve the puuid via a stub.
    import app.main as main_mod

    class StubIngest:
        def ingest(self, game_name, tag_line):
            class R:
                puuid = ME
            return R()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/audit", params={"riot_id": "Me#TAG"})
    assert r.status_code == 200
    assert "BOTTOM" in r.text
    assert "Jinx" in r.text
    assert "Suggested pool" in r.text
    assert "Draven" in r.text  # uncovered threat linked


def test_audit_invalid_riot_id(client):
    r = client.get("/audit", params={"riot_id": "no-tag"})
    assert r.status_code == 200
    assert "Invalid Riot ID" in r.text


def test_summoner_page_renders_profile(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t, region=None):
            return {"puuid": "P1", "gameName": g, "tagLine": t}

        def get_summoner_by_puuid(self, p, platform=None):
            return {"summonerLevel": 321, "profileIconId": 7}

        def get_ranked_stats(self, p, platform=None):
            return [{"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "II",
                     "leaguePoints": 44, "wins": 60, "losses": 40}]

        def get_top_mastery(self, p, count=6, platform=None):
            return [{"championId": 266, "championPoints": 123456, "championLevel": 7}]

    class StubIngest:
        _riot = StubRiot()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/summoner/euw1/Faker/KR1")
    assert r.status_code == 200
    assert "Faker#KR1" in r.text
    assert "Level 321" in r.text
    assert "Gold II" in r.text  # tier title-cased, division raw
    assert "60% WR" in r.text
    assert "Aatrox" in r.text and "123,456 pts" in r.text
    low = r.text.lower()
    assert "mmr" not in low and "elo" not in low  # framing holds on the profile too


def test_summoner_page_insights_from_stored_matches(client, monkeypatch):
    # StubRiot resolves to ME, whose Jinx games the fixture seeded → the
    # insights section renders aggregates instead of the empty state.
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t, region=None):
            return {"puuid": ME, "gameName": g, "tagLine": t}

        def get_summoner_by_puuid(self, p, platform=None):
            return None

        def get_ranked_stats(self, p, platform=None):
            return None

        def get_top_mastery(self, p, count=6, platform=None):
            return None

    class StubIngest:
        _riot = StubRiot()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/summoner/euw1/Me/TAG")
    assert r.status_code == 200
    assert "Coaching insights" in r.text
    assert "Win rate" in r.text and "KDA" in r.text
    assert "No stored matches yet" not in r.text


def test_summoner_page_not_found(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t, region=None):
            return None

    class StubIngest:
        _riot = StubRiot()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/summoner/euw1/Ghost/NONE")
    assert r.status_code == 200
    assert "Player not found" in r.text


def test_matches_page_lists_stored_games(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_account_by_riot_id(self, g, t, region=None):
            return {"puuid": ME, "gameName": g, "tagLine": t}

    class StubIngest:
        _riot = StubRiot()

        def ingest(self, g, t, platform=None):
            class R:
                puuid = ME
            return R()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/summoner/euw1/Me/TAG/matches")
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


def test_match_page_gold_chart(client):
    from app import db as db_mod

    frames = []
    for i, d in enumerate([0, 800, -400, 1200]):
        pf = {str(p): {"totalGold": 1000 + (d if p == 1 else 0)} for p in range(1, 6)}
        pf.update({str(p): {"totalGold": 1000} for p in range(6, 11)})
        frames.append({"timestamp": i * 60000, "participantFrames": pf})
    m = lane_match("EUN1_G", "Jinx", "Caitlyn", True, a_puuid=ME)
    with db_mod.open_session() as s:
        store.insert_match_bundle(s, m, {"info": {"frames": frames}}, region="europe")

    r = client.get("/match/EUN1_G")
    assert r.status_code == 200
    assert "Gold difference" in r.text
    assert "<svg" in r.text and "BLUE LEAD" in r.text and "RED LEAD" in r.text


def test_match_page_not_stored(client):
    r = client.get("/match/EUN1_999")
    assert r.status_code == 200
    assert "Match not stored" in r.text


def test_leaderboard_bare_url_redirects(client):
    r = client.get("/leaderboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/leaderboard/RANKED_SOLO_5x5"


def test_leaderboard_page_renders_ladder(client, monkeypatch):
    import app.main as main_mod

    class StubRiot:
        def get_apex_league(self, tier, queue="RANKED_SOLO_5x5", platform=None):
            return {"tier": tier, "entries": [
                {"summonerName": "Hide on bush", "leaguePoints": 1500, "wins": 200,
                 "losses": 100, "hotStreak": True, "summonerId": "x"}]}

    class StubIngest:
        _riot = StubRiot()

    monkeypatch.setattr(main_mod, "_ingest_service", StubIngest())
    r = client.get("/leaderboard/RANKED_SOLO_5x5", params={"tier": "CHALLENGER"})
    assert r.status_code == 200
    assert "Hide on bush" in r.text
    assert "1,500" in r.text  # LP thousands-formatted
    assert "Challenger" in r.text and "Grandmaster" in r.text  # tier tabs
    low = r.text.lower()
    assert "mmr" not in low and "elo" not in low


def test_champion_index_aggregate(client):
    # Direct check of the SQL aggregate the meta page uses (client fixture DB):
    # Jinx 4 games (2W), Caitlyn 5 games (4W... from specs), sorted by games.
    from app import builds
    from app import db as db_mod

    with db_mod.open_session() as s:
        rows = builds.champion_index(s)
    by_name = {r["champion"]: r for r in rows}
    assert by_name["Jinx"]["games"] == 4
    assert by_name["Jinx"]["role"] == "BOTTOM"
    assert rows == sorted(rows, key=lambda d: -d["games"])


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


def test_champion_page_is_cached(client, monkeypatch):
    from app import builds, web

    r = client.get("/champion/Jinx")
    assert r.status_code == 200 and "jinx" in web._champ_cache

    # A repeat view (any casing) must be served from the cache, not the DB.
    def boom(*a, **kw):
        raise AssertionError("cache miss: aggregate recomputed")

    monkeypatch.setattr(builds, "build_for_champion", boom)
    r2 = client.get("/champion/JINX")
    assert r2.status_code == 200 and "Caitlyn" in r2.text

    # An expired entry serves the stale page instantly — the refresh happens
    # off-thread (stale-while-revalidate), so a visitor never waits on it.
    web._champ_cache["jinx"] = (0.0, b"stale")
    r3 = client.get("/champion/Jinx")
    assert r3.status_code == 200 and r3.text == "stale"


def test_champion_refresh_repopulates_cache(client):
    import time

    from app import web

    web._champ_cache["jinx"] = (0.0, b"stale")
    web._refresh_champion_page("Jinx")  # the background worker, run inline
    expires, body = web._champ_cache["jinx"]
    assert expires > time.time() and b"Caitlyn" in body


def test_champion_warmup_prerenders_pages(client):
    from app import web

    warmed = web.warm_champion_pages()
    assert warmed >= 2  # the fixture seeds Jinx and Caitlyn with enough games
    assert "jinx" in web._champ_cache and "caitlyn" in web._champ_cache
    assert web.warm_champion_pages() == 0  # everything fresh → no-op sweep


def test_champion_page_unknown_name_not_cached(client):
    from app import web

    r = client.get("/champion/Teemo")
    assert r.status_code == 200 and "Not enough games" in r.text
    assert web._champ_cache == {}  # arbitrary URL input must not grow the dict


def test_no_skill_rating_vocabulary(client):
    # ToS framing: the public pages never talk about MMR/ELO/skill ratings.
    # ("never player skill" in the footer is the allowed, deliberate phrasing.)
    forbidden = ("mmr", "elo", "skill rating", "skill score", "matchmaking rating")
    for path in ("/", "/audit", "/download", "/champions", "/champion/Jinx"):
        text = client.get(path).text.lower()
        for word in forbidden:
            assert word not in text, f"{word!r} leaked into {path}"


def test_brand_refresh_assets(client):
    # Graphite Volt brand fidelity: fonts loaded, Signal-S mark and amber token present.
    text = client.get("/").text
    assert "Space+Grotesk" in text  # font stylesheet link
    assert 'aria-label="Sylqon"' in text  # Signal-S mark rendered in the header
    assert "--accent-2" in text  # amber secondary token in the palette


def test_champions_plural_detail_redirects(client):
    r = client.get("/champions/Lux", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/champion/Lux"
    r = client.get("/champions/Aurelion%20Sol", follow_redirects=False)
    assert r.headers["location"] == "/champion/Aurelion%20Sol"

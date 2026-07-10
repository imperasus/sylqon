"""Leaderboard shaping + TTL cache, mocked Riot client, fully offline."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import leaderboard
from app.models import Base


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class FakeRiot:
    def __init__(self, league, accounts=None):
        self.league = league
        self.calls = 0
        self.resolve_calls = 0
        # summoner_id → riot-id parts; None → resolution fails for that id
        self.accounts = accounts or {}

    def get_apex_league(self, tier, queue="RANKED_SOLO_5x5", platform=None):
        self.calls += 1
        return self.league

    def get_summoner_by_id(self, summoner_id, platform=None):
        self.resolve_calls += 1
        return {"puuid": f"puuid-{summoner_id}"} if summoner_id in self.accounts else None

    def get_account_by_puuid(self, puuid, region=None):
        self.resolve_calls += 1
        sid = puuid.removeprefix("puuid-")
        entry = self.accounts.get(sid)
        return {"gameName": entry[0], "tagLine": entry[1]} if entry else None


def _league(n=3):
    return {"tier": "CHALLENGER", "entries": [
        {"summonerName": f"P{i}", "leaguePoints": 100 * i, "wins": i, "losses": 1,
         "hotStreak": i == 2, "summonerId": f"id{i}"}
        for i in range(1, n + 1)]}


def _get(factory, riot, **kw):
    with factory() as s:
        return leaderboard.get_leaderboard(s, riot, "CHALLENGER", "RANKED_SOLO_5x5", "euw1", **kw)


def test_shape_sorts_by_lp_desc_and_ranks(factory):
    data = _get(factory, FakeRiot(_league(3)))
    assert [r["name"] for r in data["rows"]] == ["P3", "P2", "P1"]  # LP 300 > 200 > 100
    assert data["rows"][0]["rank"] == 1 and data["rows"][0]["lp"] == 300
    assert data["rows"][0]["winrate"] == 75  # 3 wins / 4 games
    assert data["rows"][1]["hot_streak"] is True  # P2


def test_snapshot_cached_within_ttl(factory):
    riot = FakeRiot(_league(3))
    _get(factory, riot)
    _get(factory, riot)  # second call served from the fresh snapshot
    assert riot.calls == 1


def test_stale_snapshot_refetches(factory):
    riot = FakeRiot(_league(2))
    _get(factory, riot, ttl=0)
    _get(factory, riot, ttl=0)  # ttl=0 → always stale
    assert riot.calls == 2


def test_blank_name_falls_back_to_short_id(factory):
    league = {"tier": "CHALLENGER", "entries": [
        {"summonerName": "", "summonerId": "abcdefghij", "leaguePoints": 500,
         "wins": 10, "losses": 0}]}
    data = _get(factory, FakeRiot(league))  # no accounts → resolution fails
    assert data["rows"][0]["name"] == "abcdefgh…"


def test_blank_name_resolved_to_riot_id(factory):
    league = {"tier": "CHALLENGER", "entries": [
        {"summonerName": "", "summonerId": "sid1", "leaguePoints": 500,
         "wins": 10, "losses": 0}]}
    riot = FakeRiot(league, accounts={"sid1": ("Hide on bush", "KR1")})
    data = _get(factory, riot)
    assert data["rows"][0]["name"] == "Hide on bush#KR1"
    assert riot.resolve_calls == 2  # summoner + account


def test_resolved_names_cached_across_refreshes(factory):
    league = {"tier": "CHALLENGER", "entries": [
        {"summonerName": "", "summonerId": "sid1", "leaguePoints": 500,
         "wins": 10, "losses": 0}]}
    riot = FakeRiot(league, accounts={"sid1": ("Faker", "KR1")})
    _get(factory, riot, ttl=0)
    _get(factory, riot, ttl=0)  # snapshot stale → refetch, but the name is cached
    assert riot.calls == 2
    assert riot.resolve_calls == 2  # only the first refresh resolved


def test_fetch_failure_serves_stale_snapshot(factory):
    riot = FakeRiot(_league(2))
    _get(factory, riot, ttl=0)  # seed a snapshot
    riot.league = None  # API now failing
    data = _get(factory, riot, ttl=0)
    assert data is not None and data["rows"][0]["name"] == "P2"

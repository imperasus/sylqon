"""Leaderboard shaping, TTL cache and Riot-ID resolution — mocked client,
fully offline. The ``factory`` fixture comes from tests/conftest.py.

League-V4 apex entries carry only a puuid (no summoner name/id) — names come
from Account-V1, a bounded number per refresh, cached permanently.
"""
from app import leaderboard


class FakeRiot:
    def __init__(self, league, accounts=None):
        self.league = league
        self.calls = 0
        self.resolve_calls = 0
        # puuid → (gameName, tagLine); missing → resolution fails for that row
        self.accounts = accounts or {}

    def get_apex_league(self, tier, queue="RANKED_SOLO_5x5", platform=None):
        self.calls += 1
        return self.league

    def get_account_by_puuid(self, puuid, region=None):
        self.resolve_calls += 1
        entry = self.accounts.get(puuid)
        return {"gameName": entry[0], "tagLine": entry[1]} if entry else None


def _league(n=3):
    """Entries the way League-V4 returns them today: puuid, no name fields."""
    return {"tier": "CHALLENGER", "entries": [
        {"puuid": f"pu{i}", "leaguePoints": 100 * i, "wins": i, "losses": 1,
         "hotStreak": i == 2}
        for i in range(1, n + 1)]}


def _accounts(n=3):
    return {f"pu{i}": (f"P{i}", "EUW") for i in range(1, n + 1)}


def _get(factory, riot, **kw):
    with factory() as s:
        return leaderboard.get_leaderboard(s, riot, "CHALLENGER", "RANKED_SOLO_5x5", "euw1", **kw)


def test_shape_sorts_by_lp_and_resolves_names(factory):
    data = _get(factory, FakeRiot(_league(3), _accounts(3)))
    assert [r["name"] for r in data["rows"]] == ["P3#EUW", "P2#EUW", "P1#EUW"]
    assert data["rows"][0]["rank"] == 1 and data["rows"][0]["lp"] == 300
    assert data["rows"][0]["winrate"] == 75  # 3 wins / 4 games
    assert data["rows"][1]["hot_streak"] is True  # pu2


def test_snapshot_cached_within_ttl(factory):
    riot = FakeRiot(_league(3), _accounts(3))
    _get(factory, riot)
    _get(factory, riot)  # second call served from the fresh snapshot
    assert riot.calls == 1


def test_stale_snapshot_refetches(factory):
    riot = FakeRiot(_league(2), _accounts(2))
    _get(factory, riot, ttl=0)
    _get(factory, riot, ttl=0)  # ttl=0 → always stale
    assert riot.calls == 2


def test_resolved_ids_cached_across_refreshes(factory):
    riot = FakeRiot(_league(2), _accounts(2))
    _get(factory, riot, ttl=0)
    _get(factory, riot, ttl=0)  # ladder refetched, but the ids come from cache
    assert riot.calls == 2
    assert riot.resolve_calls == 2  # only the first refresh resolved


def test_resolution_budget_fills_progressively(factory, monkeypatch):
    monkeypatch.setattr(leaderboard, "RESOLVE_PER_REFRESH", 2)
    riot = FakeRiot(_league(5), _accounts(5))
    first = _get(factory, riot, ttl=0)
    assert sum(1 for r in first["rows"] if r["name"]) == 2  # budget-bound
    second = _get(factory, riot, ttl=0)  # next refresh continues down the board
    assert sum(1 for r in second["rows"] if r["name"]) == 4
    assert riot.resolve_calls == 4


def test_resolution_failure_leaves_placeholder_and_retries(factory):
    riot = FakeRiot(_league(1))  # no accounts → Account-V1 returns None
    first = _get(factory, riot, ttl=0)
    assert first["rows"][0]["name"] == ""  # renders as a dash, not garbage
    riot.accounts = _accounts(1)  # Riot recovers
    second = _get(factory, riot, ttl=0)
    assert second["rows"][0]["name"] == "P1#EUW"


def test_fetch_failure_serves_stale_snapshot(factory):
    riot = FakeRiot(_league(2), _accounts(2))
    _get(factory, riot, ttl=0)  # seed a snapshot
    riot.league = None  # API now failing
    data = _get(factory, riot, ttl=0)
    assert data is not None and data["rows"][0]["name"] == "P2#EUW"

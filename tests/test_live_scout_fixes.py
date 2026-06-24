"""Offline tests for the live-scout / ban-suggestion fixes found during the demo.

Covers:
- _riot_self_puuid: full LCU puuid, RIOT_SELF_PUUID override, ACCOUNT-V1
  resolution (+ caching), graceful fallback to the short id
- _await_active_game: retries until found, stops on game end, gives up
- _ban_suggestions / _db_role_rows: DB fallback when meta_report.json is absent

No LCU, Ollama, or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.runtime import PipelineRunner


class _Ctx:
    my_role = "bottom"
    my_champion = "Caitlyn"
    enemies: list = []
    allies: list = []
    bans: list = []


def _runner() -> PipelineRunner:
    return PipelineRunner()


# --------------------------------------------------------------- #2 PUUID
def test_self_puuid_uses_full_lcu_when_present():
    r = _runner()
    r._my_puuid = "P" * 78
    assert r._riot_self_puuid() == "P" * 78


def test_self_puuid_config_override(monkeypatch):
    from sylqon import config
    r = _runner()
    r._my_puuid = "a2dab73d-316d-5f39"  # short id
    monkeypatch.setattr(config, "RIOT_SELF_PUUID", "C" * 78)
    assert r._riot_self_puuid() == "C" * 78


def test_self_puuid_resolves_via_account_v1_and_caches(monkeypatch):
    from sylqon import config
    import sylqon.riot.api as api
    r = _runner()
    r._my_puuid = "a2dab73d-316d-5f39"
    r._my_riot_id = ("Imperasus", "EUNE")
    monkeypatch.setattr(config, "RIOT_SELF_PUUID", "")
    monkeypatch.setattr(config, "RIOT_API_KEY", "fake-key")
    calls = []
    monkeypatch.setattr(api, "get_account_by_riot_id",
                        lambda g, t: calls.append((g, t)) or {"puuid": "R" * 78})
    assert r._riot_self_puuid() == "R" * 78
    r._riot_self_puuid()  # second call must use the cache
    assert calls == [("Imperasus", "EUNE")]


def test_self_puuid_falls_back_to_short_when_unresolvable(monkeypatch):
    from sylqon import config
    r = _runner()
    r._my_puuid = "shortid"
    r._my_riot_id = ("", "")  # no Riot ID to resolve with
    monkeypatch.setattr(config, "RIOT_SELF_PUUID", "")
    monkeypatch.setattr(config, "RIOT_API_KEY", "fake-key")
    assert r._riot_self_puuid() == "shortid"


# --------------------------------------------------------------- #1 retry
def test_await_active_game_retries_until_found(monkeypatch):
    import sylqon.riot.api as api
    r = _runner()
    seq = [None, None, {"participants": [{"puuid": "a"}]}]
    monkeypatch.setattr(api, "get_active_game_by_puuid", lambda pu: seq.pop(0))
    game = r._await_active_game("pu", attempts=5, interval=0)
    assert isinstance(game, dict) and game["participants"]


def test_await_active_game_stops_when_game_ends(monkeypatch):
    import sylqon.riot.api as api
    r = _runner()
    monkeypatch.setattr(api, "get_active_game_by_puuid", lambda pu: None)
    r._live_stop.set()  # game ended
    assert r._await_active_game("pu", attempts=50, interval=0) is None


def test_await_active_game_gives_up(monkeypatch):
    import sylqon.riot.api as api
    r = _runner()
    monkeypatch.setattr(api, "get_active_game_by_puuid", lambda pu: None)
    assert r._await_active_game("pu", attempts=3, interval=0) is None


# --------------------------------------------------------------- #5 ban fallback
def test_ban_suggestions_uses_db_when_meta_report_empty(monkeypatch):
    r = _runner()
    monkeypatch.setattr(r, "_meta_positions", lambda: {})  # no meta_report.json
    monkeypatch.setattr(r, "_db_role_rows", lambda role: [
        {"champion": "Aatrox", "slug": "Aatrox", "tier": 1, "win_rate": 52.0, "pick_rate": 8.0},
        {"champion": "Garen", "slug": "Garen", "tier": 2, "win_rate": 51.0, "pick_rate": 7.0},
    ])
    monkeypatch.setattr(r.store, "get_pool", lambda: {})
    out = r._ban_suggestions(_Ctx(), limit=2)
    assert [b["name"] for b in out] == ["Aatrox", "Garen"]
    assert out[0]["tier"] == 1


def test_ban_suggestions_empty_when_no_source(monkeypatch):
    r = _runner()
    monkeypatch.setattr(r, "_meta_positions", lambda: {})
    monkeypatch.setattr(r, "_db_role_rows", lambda role: [])
    assert r._ban_suggestions(_Ctx()) == []


def test_db_role_rows_shapes_and_sorts(monkeypatch):
    r = _runner()
    import sylqon.db.session as sess
    import sylqon.db.queries as q

    class C:
        def __init__(self, name, slug, stats):
            self.name, self.slug, self.op_gg_stats = name, slug, stats

    class DummySession:
        def close(self):
            pass

    monkeypatch.setattr(sess, "get_session", lambda: DummySession())
    monkeypatch.setattr(q, "champions_for_role", lambda s, role: [
        C("Garen", "Garen", {"bottom": {"tier": 2, "win_rate": 51.0, "pick_rate": 7.0}}),
        C("Aatrox", "Aatrox", {"bottom": {"tier": 1, "win_rate": 52.0, "pick_rate": 8.0}}),
    ])
    rows = r._db_role_rows("bottom")
    assert [x["champion"] for x in rows] == ["Aatrox", "Garen"]  # tier 1 first
    assert rows[0]["win_rate"] == 52.0 and rows[0]["slug"] == "Aatrox"

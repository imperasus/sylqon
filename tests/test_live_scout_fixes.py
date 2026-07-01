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
    import sylqon.riot.api as api
    from sylqon import config
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
    import sylqon.db.queries as q
    import sylqon.db.session as sess

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


# ----------------------------------------------- live-scout merge dedup
def _ally(name, puuid, games=12):
    """An existing LCU champ-select ally entry (the richer fingerprint)."""
    return {"name": name, "puuid": puuid, "side": "ally", "position": "top",
            "is_self": False, "games_analyzed": games,
            "champion_pool": [{"champion_id": 1}], "rank": ""}


def _spec(name, puuid, side, champion_id=64):
    """A spectator-scouted player entry as built by _do_live_scout."""
    return {"name": name, "puuid": puuid, "side": side, "position": "top",
            "games_analyzed": 5, "champion_id": champion_id,
            "rank": "G2 · 50 LP", "account": {"rank": "G2 · 50 LP"},
            "current_champ": {"games": 3}, "premade_group": None,
            "premade_partners": None}


_ENC = lambda i: f"ENC{'x' * 72}{i}"   # spectator-style encrypted puuid
_ENE = lambda i: f"ENE{'x' * 72}{i}"


def test_on_live_scout_dedups_allies_by_name_when_puuids_differ():
    # The 15-instead-of-10 bug: champ select gives short ids, spectator gives
    # encrypted puuids, so the puuid-only merge never collapsed the two sources.
    r = _runner()
    allies = [_ally(f"Ally{i}", f"short-{i}") for i in range(5)]
    r.state.set("scout", {"players": allies, "ready": True, "at": 0})
    spectator = ([_spec(f"Ally{i}", _ENC(i), "ally") for i in range(5)]
                 + [_spec(f"Enemy{i}", _ENE(i), "enemy") for i in range(5)])

    r._on_live_scout(spectator, premade_groups=0)
    out = r.state.snapshot()["scout"]["players"]

    assert len(out) == 10
    a0 = next(p for p in out if p["name"] == "Ally0")
    assert a0["games_analyzed"] == 12     # richer LCU fingerprint kept
    assert a0["puuid"] == _ENC(0)         # spectator puuid adopted for premades
    assert a0["rank"] == "G2 · 50 LP"     # Riot-only field overlaid
    assert a0["current_champ"] == {"games": 3}


def test_on_live_scout_dedups_allies_by_puuid_with_differing_name():
    # When the puuids DO match, a differing spectator name must not split the row.
    r = _runner()
    allies = [_ally(f"Ally{i}", _ENC(i)) for i in range(5)]
    r.state.set("scout", {"players": allies})
    spectator = ([_spec(f"DiffName{i}", _ENC(i), "ally") for i in range(5)]
                 + [_spec(f"Enemy{i}", _ENE(i), "enemy") for i in range(5)])

    r._on_live_scout(spectator)
    out = r.state.snapshot()["scout"]["players"]

    assert len(out) == 10
    a0 = next(p for p in out if p["puuid"] == _ENC(0))
    assert a0["games_analyzed"] == 12     # matched by puuid, LCU value kept


def test_on_live_scout_is_idempotent():
    # A second spectator pass must not duplicate enemies (no stable LCU puuid).
    r = _runner()
    allies = [_ally(f"Ally{i}", f"short-{i}") for i in range(5)]
    r.state.set("scout", {"players": allies})
    spectator = ([_spec(f"Ally{i}", _ENC(i), "ally") for i in range(5)]
                 + [_spec(f"Enemy{i}", _ENE(i), "enemy") for i in range(5)])

    r._on_live_scout(spectator)
    r._on_live_scout(spectator)
    out = r.state.snapshot()["scout"]["players"]

    assert len(out) == 10


def test_on_live_scout_preserves_ally_spectator_never_covered():
    # No Riot API key / custom game: spectator can't cover an ally, so the
    # LCU-only entry must survive instead of vanishing from the board.
    r = _runner()
    r.state.set("scout", {"players": [_ally("Ghost", "short-ghost")]})

    r._on_live_scout([_spec("Other", _ENC(0), "ally")])
    out = r.state.snapshot()["scout"]["players"]

    assert sorted(p["name"] for p in out) == ["Ghost", "Other"]


# ------------------------------------------ two-phase streaming (1+2)
def test_patch_scout_players_applies_deep_and_preserves_lcu_ally():
    # A deep_pending Riot-only card takes the full fingerprint overlay; a
    # richer LCU ally (no deep_pending) keeps its pool — only Riot-only fields.
    r = _runner()
    r.state.set("scout", {"players": [
        {"puuid": "E", "side": "enemy", "deep_pending": True,
         "games_analyzed": 0, "champion_pool": [], "current_champ": {}},
        {"puuid": "A", "side": "ally", "games_analyzed": 12,   # LCU-rich
         "champion_pool": [{"champion_id": 1}], "current_champ": {}},
        {"puuid": "Z", "side": "enemy", "deep_pending": True,  # untouched
         "games_analyzed": 0},
    ], "ready": True, "at": 0})

    r._patch_scout_players({
        "E": {"deep_pending": False, "games_analyzed": 7,
              "champion_pool": [{"champion_id": 64}], "current_champ": {"games": 5}},
        "A": {"deep_pending": False, "games_analyzed": 30,
              "champion_pool": [{"champion_id": 99}], "current_champ": {"games": 9}},
    }, premade_groups=2)
    out = {p["puuid"]: p for p in r.state.snapshot()["scout"]["players"]}

    assert out["E"]["games_analyzed"] == 7                 # full fingerprint applied
    assert out["E"]["champion_pool"] == [{"champion_id": 64}]
    assert out["E"]["deep_pending"] is False
    assert out["A"]["games_analyzed"] == 12                # LCU pool preserved
    assert out["A"]["champion_pool"] == [{"champion_id": 1}]
    assert out["A"]["current_champ"] == {"games": 9}       # Riot-only field overlaid
    assert out["Z"]["deep_pending"] is True                # not in patches → untouched
    assert r.state.snapshot()["scout"]["premade_groups"] == 2


def test_do_live_scout_shows_all_ten_before_deep_stats(monkeypatch):
    # The whole point of 1+2: a full 10-card push happens (Phase A) *before* any
    # match-history fingerprint resolves, then deep stats stream in (Phase B).
    import sylqon.riot.api as riot_api
    import sylqon.riot.scout as riot_scout
    from sylqon.lcu.scout import PlayerFingerprint

    r = _runner()
    monkeypatch.setattr(r, "_name_slug", lambda e: None)
    parts = [{"puuid": f"P{i}", "championId": 10 + i,
              "teamId": 100 if i < 5 else 200,
              "riotId": f"Name{i}#TAG", "teamPosition": "TOP"} for i in range(10)]
    monkeypatch.setattr(r, "_await_active_game", lambda pu: {"participants": parts})
    monkeypatch.setattr(riot_scout, "scout_account",
                        lambda pu: ({"rank": "G2 · 50 LP", "mastery": []}, []))
    monkeypatch.setattr(riot_scout, "scout_history",
                        lambda pu, mastery=None: (
                            PlayerFingerprint(games_analyzed=8,
                                              champion_pool=[{"champion_id": 64}]),
                            {"g1": {pu: 100}}))
    monkeypatch.setattr(riot_api, "get_mastery_by_champion", lambda pu, cid: None)
    monkeypatch.setattr(riot_scout, "detect_premades", lambda puuids, cm: [])

    scout_pushes: list = []
    orig_set = r.state.set
    monkeypatch.setattr(r.state, "set", lambda sec, val: (
        scout_pushes.append(val) if sec == "scout" else None, orig_set(sec, val))[-1])

    r._do_live_scout("P0")

    # Phase A: the first scout push already has all 10 cards, none with deep stats.
    phase_a = scout_pushes[0]
    assert len(phase_a["players"]) == 10
    assert all(p["deep_pending"] for p in phase_a["players"])
    assert all(p["games_analyzed"] == 0 for p in phase_a["players"])
    # Streaming: 1 (Phase A) + 10 (per-player) + 1 (premade) pushes.
    assert len(scout_pushes) == 12

    final = {p["puuid"]: p for p in r.state.snapshot()["scout"]["players"]}
    assert len(final) == 10
    assert all(p["games_analyzed"] == 8 for p in final.values())
    assert all(p["deep_pending"] is False for p in final.values())
    assert final["P2"]["side"] == "ally" and final["P7"]["side"] == "enemy"

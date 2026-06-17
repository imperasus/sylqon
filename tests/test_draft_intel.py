"""Offline tests for the live-draft intelligence layer.

Covers the pure composition classifier and counter-pick timing advice, plus the
lobby session parsing for bans and pick order. No LCU, DB or Ollama required.

Run: python -m pytest tests/test_draft_intel.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis import draft_intel
from sylqon.lcu.lobby import (
    ChampPick, MatchContext, _banned_champions, _pick_timing,
    display_signature, parse_bans,
)


class _Catalog:
    """Minimal catalog stub: champion id -> {name, id(slug)}."""

    def __init__(self, by_key):
        self._by_key = by_key

    def champion_by_key(self, cid):
        return self._by_key.get(cid)


def _pick(name, *, side="enemy", role="middle", dmg="AP", tags=(), threats=()):
    return ChampPick(name=name, champion_id=hash(name) % 1000, role=role,
                     side=side, damage_type=dmg, tags=list(tags),
                     threats=list(threats))


# -- classify_comp -----------------------------------------------------------
def test_poke_comp_detected():
    picks = [
        _pick("Xerath", threats=["poke", "burst_ap"]),
        _pick("Varus", tags=["Marksman"], threats=["poke"]),
        _pick("Ziggs", threats=["poke"]),
    ]
    out = draft_intel.classify_comp(picks)
    assert out["archetype"] == "poke_siege"
    assert out["confidence"] > 0
    assert any("poke" in s for s in out["signals"])


def test_hard_engage_comp_detected():
    picks = [
        _pick("Leona", tags=["Tank", "Support"], threats=["heavy_cc"]),
        _pick("Malphite", tags=["Tank"], threats=["heavy_cc", "tank"]),
        _pick("Sejuani", tags=["Tank", "Fighter"], threats=["heavy_cc", "tank"]),
    ]
    out = draft_intel.classify_comp(picks)
    assert out["archetype"] == "hard_engage"
    assert "Dive" in out["label"] or "Engage" in out["label"]


def test_too_few_picks_is_unknown():
    out = draft_intel.classify_comp([_pick("Ahri")])
    assert out["archetype"] == "unknown"
    assert out["confidence"] == 0


def test_classify_accepts_dict_shape():
    picks = [
        {"name": "Zed", "tags": ["Assassin"], "damage_type": "AD", "threats": ["burst_ad"]},
        {"name": "Talon", "tags": ["Assassin"], "damage_type": "AD", "threats": ["burst_ad"]},
    ]
    out = draft_intel.classify_comp(picks)
    assert out["archetype"] == "pick"


# -- counter_pick_advice -----------------------------------------------------
def _ctx(**kw):
    base = dict(summoner_id=1, my_champion="", my_champion_id=0, my_role="middle",
                locked=False, all_locked=False, my_turn=False, enemies=[], allies=[],
                fingerprint="x")
    base.update(kw)
    return MatchContext(**base)


def test_last_pick_gets_counter_window():
    ctx = _ctx(my_turn=True, enemy_picks_after_me=0)
    assert draft_intel.counter_pick_advice(ctx)["phase"] == "counter"


def test_blind_pick_warned():
    ctx = _ctx(my_turn=True, enemy_picks_after_me=2)
    advice = draft_intel.counter_pick_advice(ctx)
    assert advice["phase"] == "blind"
    assert "2" in advice["headline"]


def test_waiting_when_not_our_turn():
    ctx = _ctx(my_turn=False, enemies=[_pick("Ahri")])
    assert draft_intel.counter_pick_advice(ctx)["phase"] == "waiting"


def test_locked_phase():
    ctx = _ctx(locked=True, my_turn=False)
    assert draft_intel.counter_pick_advice(ctx)["phase"] == "locked"


# -- lobby session parsing ---------------------------------------------------
def _session():
    # cell 0 = us (myTeam), cells 5/6 = enemies (theirTeam). Pick order: us, then
    # an enemy still to come.
    return {
        "theirTeam": [{"cellId": 5}, {"cellId": 6}],
        "actions": [
            [{"type": "ban", "completed": True, "championId": 21}],
            [{"type": "ban", "completed": False, "championId": 99}],  # not locked
            [{"type": "pick", "actorCellId": 5, "completed": True}],
            [{"type": "pick", "actorCellId": 0, "completed": False, "isInProgress": True}],
            [{"type": "pick", "actorCellId": 6, "completed": False}],
        ],
    }


def test_banned_champions_only_completed():
    assert _banned_champions(_session()) == [21]


def test_pick_timing_counts_enemies_after_us():
    enemy_after, ally_after, is_last = _pick_timing(_session(), cell_id=0)
    assert enemy_after == 1
    assert ally_after == 0
    assert is_last is False


def test_pick_timing_last_pick():
    session = _session()
    # drop the trailing enemy pick so we are the last actor
    session["actions"] = session["actions"][:-1]
    enemy_after, _, is_last = _pick_timing(session, cell_id=0)
    assert enemy_after == 0
    assert is_last is True


# -- bans (per-team, slot/placeholder aware) ---------------------------------
def _ban_session():
    return {
        "myTeam": [{"cellId": 0}, {"cellId": 1}],
        "actions": [
            [{"type": "ban", "completed": True, "championId": 21, "isAllyAction": True}],
            [{"type": "ban", "completed": True, "championId": 54, "isAllyAction": False}],
            [{"type": "ban", "completed": False, "championId": 0, "isAllyAction": True}],   # pending
            [{"type": "ban", "completed": False, "championId": 0, "isAllyAction": False}],  # hidden hover
        ],
    }


def test_parse_bans_splits_teams_and_reveals():
    catalog = _Catalog({21: {"name": "Miss Fortune", "id": "MissFortune"},
                        54: {"name": "Malphite", "id": "Malphite"}})
    bans = parse_bans(_ban_session(), catalog)
    assert [b.get("name") for b in bans["ally"] if b["revealed"]] == ["Miss Fortune"]
    assert [b.get("name") for b in bans["enemy"] if b["revealed"]] == ["Malphite"]
    # one revealed + one placeholder per team, in draft order
    assert [b["revealed"] for b in bans["ally"]] == [True, False]
    assert [b["revealed"] for b in bans["enemy"]] == [True, False]


def test_parse_bans_falls_back_to_cell_mapping():
    """Without isAllyAction, actor cells decide the side."""
    session = {
        "myTeam": [{"cellId": 0}],
        "actions": [[{"type": "ban", "completed": True, "championId": 7, "actorCellId": 0}]],
    }
    bans = parse_bans(session, _Catalog({7: {"name": "LeBlanc", "id": "Leblanc"}}))
    assert bans["ally"][0]["name"] == "LeBlanc"
    assert bans["enemy"] == []


def test_parse_bans_empty_when_no_bans():
    assert parse_bans({"myTeam": [], "actions": []}, _Catalog({})) == {"ally": [], "enemy": []}


# -- display signature must react to bans (real-time gate) -------------------
def test_display_signature_moves_when_ban_completes():
    base = {
        "localPlayerCellId": 0,
        "myTeam": [{"cellId": 0, "championId": 0}],
        "theirTeam": [],
        "actions": [[{"type": "ban", "actorCellId": 5, "championId": 0, "completed": False}]],
    }
    before = display_signature(base)
    after = dict(base)
    after["actions"] = [[{"type": "ban", "actorCellId": 5, "championId": 54, "completed": True}]]
    assert display_signature(after) != before

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
)


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

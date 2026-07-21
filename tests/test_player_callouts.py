"""Offline tests for the deterministic coaching callouts (analysis/player_callouts).

Every callout must carry an action, a timing and citable evidence — these tests
pin that contract, each generator's trigger conditions, and the "evidence or
silence" rule that stops the panel drifting back into vague advice.

Run: python -m pytest tests/test_player_callouts.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis import player_callouts as pc


def card(**kw):
    """A scout card with sane, signal-free defaults; override what's under test."""
    base = {
        "name": "Player", "champion": "Champ", "champion_id": 1, "role": "middle",
        "side": "enemy", "is_self": False,
        "recent_form": {"games": 20, "win_rate": 0.5, "streak": 0, "avg_deaths": 5.0},
        "avg_kda": {"kills": 5.0, "deaths": 5.0, "assists": 5.0, "ratio": 2.0},
        "aggression": 0.4, "playstyle_tags": [], "comfort": None,
        "current_champ": {"games": 5, "win_rate": 0.5},
        "premade_group": None, "damage_type": "", "threats": [],
    }
    base.update(kw)
    return base


def kinds(callouts):
    return [c["kind"] for c in callouts]


def only(callouts, kind):
    return [c for c in callouts if c["kind"] == kind]


# ------------------------------------------------------------------- contract
def test_every_callout_carries_action_timing_and_evidence():
    players = [
        card(role="bottom", champion="Jinx", premade_group=0, name="A"),
        card(role="utility", champion="Leona", premade_group=0, name="B"),
        card(role="jungle", champion="Lee Sin", aggression=0.8, name="J"),
        card(role="top", champion="Darius", damage_type="AD"),
        card(role="middle", champion="Zed", damage_type="AD"),
    ]
    out = pc.build_callouts(players, my_role="top")
    assert out
    for c in out:
        assert c["action"] and c["timing"] and c["evidence"]
        assert isinstance(c["priority"], int)


def test_output_is_capped_and_priority_ordered():
    players = [
        card(role="bottom", champion="Jinx", premade_group=0, name="A"),
        card(role="utility", champion="Leona", premade_group=0, name="B"),
        card(role="jungle", champion="Lee Sin", aggression=0.9, name="J"),
        card(role="top", champion="Darius", damage_type="AD"),
        card(role="middle", champion="Zed", damage_type="AD",
             current_champ={"games": 90, "win_rate": 0.6}),
    ]
    out = pc.build_callouts(players, my_role="top", limit=3)
    assert len(out) == 3
    assert [c["priority"] for c in out] == sorted((c["priority"] for c in out), reverse=True)


def test_quiet_roster_produces_nothing():
    """No signal → no advice. Silence beats invented coaching."""
    assert pc.build_callouts([card(role=r) for r in
                              ("top", "jungle", "middle", "bottom", "utility")]) == []


# ------------------------------------------------------------------ dive risk
def test_premade_botlane_raises_a_dive_warning():
    out = pc.build_callouts([
        card(role="bottom", champion="Jinx", premade_group=1, name="A"),
        card(role="utility", champion="Leona", premade_group=1, name="B"),
    ])
    assert "dive_risk" in kinds(out)
    assert "level-2" in only(out, "dive_risk")[0]["action"]


def test_botlane_in_different_parties_is_not_a_duo():
    out = pc.build_callouts([
        card(role="bottom", premade_group=1), card(role="utility", premade_group=2),
    ])
    assert "dive_risk" not in kinds(out)


def test_solo_queued_botlane_raises_nothing():
    out = pc.build_callouts([card(role="bottom"), card(role="utility")])
    assert "dive_risk" not in kinds(out)


# -------------------------------------------------------------- jungle threat
def test_aggressive_jungler_warns_with_role_specific_warding():
    players = [card(role="jungle", champion="Lee Sin", aggression=0.8, name="J")]
    top = pc.build_callouts(players, my_role="top")
    bot = pc.build_callouts(players, my_role="bottom")
    assert "tri-brush" in only(top, "jungle_threat")[0]["action"]
    assert "tri-bush" in only(bot, "jungle_threat")[0]["action"]


def test_passive_jungler_raises_nothing():
    out = pc.build_callouts([card(role="jungle", aggression=0.3)])
    assert "jungle_threat" not in kinds(out)


def test_jungle_threat_needs_enough_games_to_cite():
    """Evidence-or-silence: a 0.9 aggression over 4 games proves nothing."""
    out = pc.build_callouts([
        card(role="jungle", aggression=0.9,
             recent_form={"games": 4, "win_rate": 0.5, "streak": 0, "avg_deaths": 5.0})])
    assert "jungle_threat" not in kinds(out)


# --------------------------------------------------------------- itemization
def test_stacked_ad_threats_suggest_armor():
    out = pc.build_callouts([card(role="top", damage_type="AD", champion="Darius"),
                             card(role="middle", damage_type="AD", champion="Zed")])
    assert "armor" in only(out, "itemization")[0]["action"]


def test_stacked_ap_threats_suggest_magic_resist():
    out = pc.build_callouts([card(role="top", damage_type="AP", champion="Rumble"),
                             card(role="middle", damage_type="AP", champion="Ahri")])
    assert "magic resist" in only(out, "itemization")[0]["action"]


def test_mixed_damage_suggests_neither():
    out = pc.build_callouts([card(role="top", damage_type="AD"),
                             card(role="middle", damage_type="AP")])
    assert not [c for c in only(out, "itemization")
                if "armor" in c["action"] or "magic resist" in c["action"]]


def test_stacked_healing_suggests_anti_heal():
    out = pc.build_callouts([
        card(role="top", champion="Aatrox", threats=["heavy_healing"]),
        card(role="utility", champion="Soraka", threats=["heavy_healing"])])
    assert any("anti-heal" in c["action"] for c in only(out, "itemization"))


# ------------------------------------------------------------------ one-trick
def test_deep_champion_mastery_is_called_out():
    out = pc.build_callouts([card(champion="Riven", name="R",
                                  current_champ={"games": 120, "win_rate": 0.62})])
    c = only(out, "one_trick")[0]
    assert "120 games on Riven" in c["evidence"]
    assert "62% WR" in c["evidence"]


def test_shallow_champion_pool_is_not_a_one_trick():
    out = pc.build_callouts([card(current_champ={"games": 3, "win_rate": 1.0})])
    assert "one_trick" not in kinds(out)


def test_comfort_share_also_marks_a_one_trick():
    out = pc.build_callouts([card(
        champion="Yasuo", current_champ={"games": 12, "win_rate": 0.5},
        comfort={"champion": "Yasuo", "share": 0.7, "games": 14, "win_rate": 0.5})])
    assert "one_trick" in kinds(out)


# ---------------------------------------------------------- fed / pressure
def test_snowballing_enemy_is_flagged():
    out = pc.build_callouts([card(champion="Katarina", kills=9, deaths=1, assists=3)])
    assert "fed_enemy" in kinds(out)


def test_even_score_is_not_fed():
    out = pc.build_callouts([card(kills=2, deaths=3, assists=1)])
    assert "fed_enemy" not in kinds(out)


def test_pressure_requires_deaths_above_baseline():
    """A losing streak alone is variance; deaths above their own norm is evidence."""
    variance = pc.build_callouts([card(
        recent_form={"games": 20, "win_rate": 0.3, "streak": -4, "avg_deaths": 5.0},
        avg_kda={"kills": 5.0, "deaths": 5.0, "assists": 5.0, "ratio": 2.0})])
    assert "pressure" not in kinds(variance)

    misplaying = pc.build_callouts([card(
        recent_form={"games": 20, "win_rate": 0.3, "streak": -4, "avg_deaths": 8.5},
        avg_kda={"kills": 5.0, "deaths": 5.0, "assists": 5.0, "ratio": 2.0})])
    assert "pressure" in kinds(misplaying)


# -------------------------------------------------------------------- allies
def test_hot_ally_is_worth_enabling():
    out = pc.build_callouts([card(
        side="ally", name="Mate", role="jungle",
        recent_form={"games": 20, "win_rate": 0.7, "streak": 4, "avg_deaths": 4.0})])
    assert "enable_ally" in kinds(out)


def test_self_is_never_a_callout_target():
    out = pc.build_callouts([card(
        side="ally", is_self=True, name="Me",
        recent_form={"games": 20, "win_rate": 0.7, "streak": 4, "avg_deaths": 4.0})])
    assert "enable_ally" not in kinds(out)


def test_hidden_players_are_ignored():
    out = pc.build_callouts([
        card(role="bottom", premade_group=1, hidden=True),
        card(role="utility", premade_group=1, hidden=True)])
    assert out == []

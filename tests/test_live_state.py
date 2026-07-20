"""Offline tests for the Live Client Data parser (overlay coach, Phase 1).

No game / network required — feeds a synthetic ``allgamedata`` payload through
``parse_live_state`` and checks the normalized snapshot.

Run: python -m pytest tests/test_live_state.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.livegame.state import LiveGameState, parse_live_state

SAMPLE = {
    "gameData": {"gameTime": 600.0, "gameMode": "CLASSIC"},
    "activePlayer": {"riotIdGameName": "Sneaky", "summonerName": "Sneaky", "level": 9},
    "allPlayers": [
        {"riotIdGameName": "Sneaky", "summonerName": "Sneaky", "championName": "Jinx",
         "team": "ORDER", "position": "BOTTOM", "level": 9, "isDead": False,
         "respawnTimer": 0.0,
         "scores": {"kills": 3, "deaths": 1, "assists": 5, "creepScore": 120,
                    "wardScore": 8.5}},
        {"riotIdGameName": "AllyJg", "summonerName": "AllyJg", "championName": "Lee Sin",
         "team": "ORDER", "position": "JUNGLE", "scores": {}},
        {"riotIdGameName": "Enemy1", "summonerName": "Enemy1", "championName": "Caitlyn",
         "team": "CHAOS", "position": "BOTTOM", "scores": {}},
    ],
    "events": {"Events": [
        {"EventID": 0, "EventName": "GameStart", "EventTime": 0.0},
        {"EventName": "ChampionKill", "KillerName": "Enemy1", "VictimName": "Sneaky",
         "EventTime": 300.0},
        {"EventName": "DragonKill", "KillerName": "AllyJg", "DragonType": "Fire",
         "EventTime": 420.0},
        {"EventName": "DragonKill", "KillerName": "Enemy1", "DragonType": "Air",
         "EventTime": 480.0},
        # Turret_T2 is a CHAOS-owned tower → destroying it is an ally objective.
        {"EventName": "TurretKilled", "TurretKilled": "Turret_T2_C_05_A",
         "KillerName": "Sneaky", "EventTime": 500.0},
    ]},
}


def test_no_game_sentinel():
    assert parse_live_state(None).active is False
    assert parse_live_state({}).active is True or parse_live_state({}) is not None
    assert LiveGameState.none().active is False


def test_parses_core_fields():
    s = parse_live_state(SAMPLE)
    assert s.active is True
    assert s.game_time == 600.0
    assert s.champion == "Jinx"
    assert s.team == "ORDER"
    assert (s.kills, s.deaths, s.assists) == (3, 1, 5)
    assert s.cs == 120
    assert s.cs_per_min == 12.0          # 120 / (600/60)
    assert s.ward_score == 8.5
    assert s.role == "bottom"            # from live position BOTTOM
    assert s.is_dead is False


def test_role_override_prefers_champ_select():
    s = parse_live_state(SAMPLE, my_role="middle")
    assert s.role == "middle"            # champ-select role wins over live position


def test_deaths_and_objectives():
    s = parse_live_state(SAMPLE)
    assert s.death_times == [300.0]
    # one ally dragon (AllyJg/ORDER), one enemy dragon (Enemy1/CHAOS)
    assert s.objectives["dragons"] == {"ally": 1, "enemy": 1}
    # destroyed a CHAOS turret while on ORDER → ally tower
    assert s.objectives["towers"]["ally"] == 1


def test_roster_tags_allies_and_enemies():
    s = parse_live_state(SAMPLE)
    by_name = {p["name"]: p for p in s.roster}
    assert set(by_name) == {"Sneaky", "AllyJg", "Enemy1"}
    # side is relative to me (ORDER): same team = ally, other = enemy.
    assert by_name["Sneaky"]["side"] == "ally"
    assert by_name["AllyJg"]["side"] == "ally"
    assert by_name["Enemy1"]["side"] == "enemy"
    # enemy carries champion + role + live stats from allPlayers (read-only).
    enemy = by_name["Enemy1"]
    assert enemy["champion"] == "Caitlyn" and enemy["role"] == "bottom"
    me = by_name["Sneaky"]
    assert (me["kills"], me["deaths"], me["assists"], me["cs"]) == (3, 1, 5, 120)


def test_live_metrics_benchmark_and_timers():
    s = parse_live_state(SAMPLE)
    # CS benchmark: bottom target 8.5, live 12.0/min → well ahead.
    assert s.cs_benchmark["target"] == 8.5
    assert s.cs_benchmark["status"] == "ahead"
    # Objective timers from kill events (game_time 600): last dragon at 480 →
    # next at 780 → 180s out; no baron kill → first baron 1200 → 600s out.
    assert s.objective_timers == {"dragon": 180, "baron": 600}
    # No enemy levels in the sample → neutral level diff.
    assert s.level_diff == 0


def test_dict_serializable():
    s = parse_live_state(SAMPLE)
    d = s.to_dict()
    assert d["active"] is True and d["cs"] == 120 and "objectives" in d
    assert len(d["roster"]) == 3 and d["roster"][0]["champion"] == "Jinx"
    assert "cs_benchmark" in d and "objective_timers" in d


# --------------------------------------------- locale-independent build read
# A non-English (Hungarian) client localizes every ``displayName``. Spells must
# still resolve via ``rawDisplayName`` and runes via their numeric ``id`` so the
# UI's English-keyed icon/abbreviation lookups keep working.
LOCALIZED = {
    "gameData": {"gameTime": 65.0},
    "activePlayer": {"riotIdGameName": "Imperasus", "level": 2},
    "allPlayers": [
        {"riotIdGameName": "Imperasus", "championName": "Yuumi", "team": "ORDER",
         "position": "UTILITY", "level": 2, "scores": {"creepScore": 0},
         "items": [
             {"itemID": 3850, "slot": 0}, {"itemID": 2003, "slot": 1},
             {"itemID": 0, "slot": 2},
         ],
         "summonerSpells": {
             "summonerSpellOne": {"displayName": "Tüzes csapás",
                 "rawDisplayName": "GeneratedTip_SummonerSpell_SummonerDot_DisplayName"},
             "summonerSpellTwo": {"displayName": "Felvillanás",
                 "rawDisplayName": "GeneratedTip_SummonerSpell_SummonerFlash_DisplayName"},
         },
         "runes": {
             "keystone": {"displayName": "Aery megidézése", "id": 8214},
             "primaryRuneTree": {"displayName": "Varázslat", "id": 8200},
             "secondaryRuneTree": {"displayName": "Elszántság", "id": 8400},
         }},
    ],
}


def test_roster_resolves_localized_spells_to_english():
    me = parse_live_state(LOCALIZED).roster[0]
    # Hungarian displayNames, but rawDisplayName resolves to canonical English.
    assert me["spells"] == ["Ignite", "Flash"]


def test_roster_resolves_localized_runes_by_id():
    me = parse_live_state(LOCALIZED).roster[0]
    assert me["runes"]["keystone"] == "Summon Aery"   # id 8214
    assert me["runes"]["primary"] == "Sorcery"        # style 8200
    assert me["runes"]["secondary"] == "Resolve"      # style 8400


def test_roster_items_drop_empty_slots_in_order():
    me = parse_live_state(LOCALIZED).roster[0]
    assert me["items"] == [3850, 2003]   # slot 2 (itemID 0) dropped


def test_runes_fall_back_to_displayname_for_unknown_id():
    from sylqon.livegame.state import _runes
    r = _runes({"runes": {"keystone": {"displayName": "Brand New Rune", "id": 99999}}})
    assert r["keystone"] == "Brand New Rune"


# ----------------------------------------------- C-delta: soul + power-spike
def test_dragon_soul_thresholds():
    from sylqon.livegame.state import _dragon_soul
    assert _dragon_soul({"dragons": {"ally": 3, "enemy": 1}})["status"] == "ally_soul_point"
    assert _dragon_soul({"dragons": {"ally": 1, "enemy": 3}})["status"] == "enemy_soul_point"
    assert _dragon_soul({"dragons": {"ally": 4, "enemy": 2}})["status"] == "ally_soul"
    assert _dragon_soul({"dragons": {"ally": 2, "enemy": 4}})["status"] == "enemy_soul"
    assert _dragon_soul({"dragons": {"ally": 2, "enemy": 1}})["status"] == ""
    assert _dragon_soul({})["status"] == ""


def test_completed_count_excludes_boots_components_consumables():
    from sylqon.livegame.state import _completed_count
    p = {"items": [
        {"itemID": 3031, "price": 3400},                    # legendary -> counts
        {"itemID": 6672, "price": 3000},                    # legendary -> counts
        {"itemID": 3006, "price": 1100},                    # boots -> below threshold
        {"itemID": 1038, "price": 1300},                    # component -> below
        {"itemID": 2055, "price": 75, "consumable": True},  # control ward -> excluded
    ]}
    assert _completed_count(p) == 2


def test_item_spike_needs_opponent_and_items():
    from sylqon.livegame.state import _item_spike
    only_me = [{"side": "ally", "role": "bottom", "completed_items": 2}]
    assert _item_spike(only_me, "bottom") == {}            # no lane opponent
    zeros = [{"side": "ally", "role": "bottom", "completed_items": 0},
             {"side": "enemy", "role": "bottom", "completed_items": 0}]
    assert _item_spike(zeros, "bottom") == {}              # nothing finished yet
    behind = [{"side": "ally", "role": "bottom", "completed_items": 1},
              {"side": "enemy", "role": "bottom", "completed_items": 2}]
    assert _item_spike(behind, "bottom") == {"mine": 1, "opponent": 2, "status": "behind"}


ITEM_SPIKE_SAMPLE = {
    "gameData": {"gameTime": 1200.0},
    "activePlayer": {"riotIdGameName": "Me", "level": 11},
    "allPlayers": [
        {"riotIdGameName": "Me", "championName": "Jinx", "team": "ORDER",
         "position": "BOTTOM", "level": 11, "scores": {"creepScore": 200},
         "items": [{"itemID": 3031, "price": 3400, "slot": 0},
                   {"itemID": 3094, "price": 2600, "slot": 1},
                   {"itemID": 3006, "price": 1100, "slot": 2}]},
        {"riotIdGameName": "Enemy", "championName": "Caitlyn", "team": "CHAOS",
         "position": "BOTTOM", "scores": {},
         "items": [{"itemID": 6672, "price": 3100, "slot": 0},
                   {"itemID": 1038, "price": 1300, "slot": 1}]},
    ],
    "events": {"Events": []},
}


def test_item_spike_and_soul_via_parse_live_state():
    s = parse_live_state(ITEM_SPIKE_SAMPLE)
    # 2 finished items (boots excluded) vs the enemy bottom's 1 → ahead.
    assert s.item_spike == {"mine": 2, "opponent": 1, "status": "ahead"}
    assert s.roster[0]["completed_items"] == 2
    # No drakes in this sample → no soul nag.
    assert s.soul["status"] == ""


# ------------------------------------------ Phase 1: extended activePlayer data
COMBAT_SAMPLE = {
    "gameData": {"gameTime": 720.0, "mapTerrain": "Infernal"},
    "activePlayer": {
        "riotIdGameName": "Me", "level": 9, "currentGold": 1450.0,
        "championStats": {
            "abilityHaste": 25.0, "attackDamage": 210.4, "abilityPower": 0.0,
            "armor": 95.6, "magicResist": 52.0, "moveSpeed": 340.0,
            "attackRange": 550.0, "currentHealth": 900.0, "maxHealth": 1800.0,
            "resourceValue": 120.0, "resourceMax": 300.0,
        },
        "abilities": {
            "Q": {"abilityLevel": 5}, "W": {"abilityLevel": 3},
            "E": {"abilityLevel": 1}, "R": {"abilityLevel": 1},
        },
    },
    "allPlayers": [
        {"riotIdGameName": "Me", "championName": "Jinx", "team": "ORDER",
         "position": "BOTTOM", "level": 9, "scores": {"creepScore": 100}},
    ],
    "events": {"Events": []},
}


def test_parses_current_gold_and_terrain():
    s = parse_live_state(COMBAT_SAMPLE)
    assert s.current_gold == 1450.0
    assert s.map_terrain == "Infernal"
    # soul type is derived from the rift terrain
    assert s.soul["type"] == "Infernal"


def test_parses_champion_stats_with_health_pct():
    s = parse_live_state(COMBAT_SAMPLE)
    cs = s.champion_stats
    assert cs["ability_haste"] == 25.0
    assert cs["attack_damage"] == 210.4
    assert cs["current_health"] == 900.0 and cs["max_health"] == 1800.0
    assert cs["health_pct"] == 50.0          # 900 / 1800
    assert cs["resource_value"] == 120.0 and cs["resource_max"] == 300.0


def test_parses_ability_levels_for_spike_detection():
    s = parse_live_state(COMBAT_SAMPLE)
    ab = s.abilities
    assert (ab["q"], ab["w"], ab["e"], ab["r"]) == (5, 3, 1, 1)
    assert ab["ult_level"] == 1              # level-6 ultimate unlocked


def test_extended_fields_degrade_gracefully_when_absent():
    # The original SAMPLE has no championStats/abilities/currentGold/mapTerrain.
    s = parse_live_state(SAMPLE)
    assert s.current_gold == 0.0
    assert s.map_terrain == ""
    assert s.abilities == {"q": 0, "w": 0, "e": 0, "r": 0, "ult_level": 0}
    assert s.champion_stats["health_pct"] == 0.0   # no max_health → safe 0
    assert s.soul["type"] == ""                     # no terrain → no soul element


def test_extended_fields_serialize():
    d = parse_live_state(COMBAT_SAMPLE).to_dict()
    assert d["current_gold"] == 1450.0
    assert d["champion_stats"]["ability_haste"] == 25.0
    assert d["abilities"]["ult_level"] == 1
    assert d["map_terrain"] == "Infernal"


# ------------------------------------------ Phase 2: accuracy improvements
def test_completed_count_prefers_catalog_then_price_fallback():
    from sylqon.livegame.state import _completed_count
    p = {"items": [
        {"itemID": 3031, "price": 3400},                    # catalog: completed → counts
        {"itemID": 1038, "price": 1300},                    # catalog: component → excluded
        {"itemID": 3006, "price": 1100},                    # catalog: boots → excluded
        {"itemID": 999999, "price": 3000},                  # unknown to catalog → price proxy
        {"itemID": 2055, "price": 75, "consumable": True},  # consumable → excluded
    ]}
    # Infinity Edge (catalog-completed) + the unknown legendary-priced item.
    assert _completed_count(p) == 2


def test_level_diff_uses_lane_opponent_not_average():
    from sylqon.livegame.state import _level_diff
    roster = [
        {"side": "enemy", "role": "bottom", "level": 8},
        {"side": "enemy", "role": "top", "level": 14},
        {"side": "enemy", "role": "middle", "level": 12},
    ]
    # Lane opponent (bottom) is level 8; my 11 → +3, NOT the enemy average (~0).
    assert _level_diff(roster, 11, "bottom") == 3
    # No same-role opponent → falls back to the enemy-team average.
    assert _level_diff(roster, 11, "jungle") == 11 - round((8 + 14 + 12) / 3)
    # No level yet on the lane opponent → also falls back gracefully.
    assert _level_diff([{"side": "enemy", "role": "bottom", "level": 0}], 5, "bottom") == 0


# ------------------------------------------ Phase 4: coaching depth
def test_last_death_captures_killer_and_collapse():
    from sylqon.livegame.state import _last_death
    events = [
        {"EventName": "ChampionKill", "VictimName": "Me", "KillerName": "EnemyMid",
         "Assisters": ["EnemyJg", "EnemySup"], "EventTime": 420.0},
    ]
    roster = [{"name": "EnemyMid", "champion": "Zed"}]
    d = _last_death(events, "Me", roster)
    assert d["killer_champ"] == "Zed"
    assert d["assisters"] == 2          # a 3-man collapse
    assert d["game_time"] == 420.0


def test_last_death_empty_when_not_died():
    from sylqon.livegame.state import _last_death
    assert _last_death([], "Me", []) == {}


def test_matchup_from_opponent_class_and_spells():
    from sylqon.livegame.state import _matchup
    roster = [{"side": "enemy", "role": "middle", "champion": "Zed",
               "spells": ["Ignite", "Flash"]}]
    m = _matchup(roster, "middle")
    assert m["opponent"] == "Zed"
    assert "all-in" in m["playstyle"].lower()      # Assassin playstyle note
    assert "ignite" in m["tempo"].lower()          # summoner-spell tempo read


def test_matchup_empty_without_lane_opponent():
    from sylqon.livegame.state import _matchup
    assert _matchup([{"side": "ally", "role": "middle", "champion": "Ahri"}], "middle") == {}
    assert _matchup([], "") == {}


def test_mission_dict_carries_rationale():
    from sylqon.livegame.engine import MissionEngine
    from sylqon.livegame.missions import ROLE_CATALOG, make_runtime
    m = ROLE_CATALOG["middle"][0]
    rt = make_runtime(m, parse_live_state(SAMPLE, my_role="middle"))
    d = MissionEngine._mission_dict(rt)
    assert d["rationale"]                            # per-type default is filled in


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))

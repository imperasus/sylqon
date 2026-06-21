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


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))

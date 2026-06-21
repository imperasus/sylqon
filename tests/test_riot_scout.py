"""Offline tests for Riot API-based live-game scouting (sylqon/riot/scout.py).

Cover the pure helpers — premade detection, current-champ stats, account
summary, rank labels — plus a fully monkeypatched ``scout_puuid`` that verifies
the Summoner's Rift queue filter (Normal Draft counts, ARAM/bots don't) and the
``comatches`` shape premade detection consumes. No network, no API key required.

Run: python -m pytest tests/test_riot_scout.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.lcu.scout import PlayerFingerprint
from sylqon.riot import api
from sylqon.riot import scout as rs


# ----------------------------------------------------------- rank / account
def test_rank_label_formats_and_empty():
    assert rs.rank_label({"tier": "GOLD", "rank": "II", "leaguePoints": 67}) == "G2 · 67 LP"
    assert rs.rank_label({"tier": "MASTER", "rank": "", "leaguePoints": 312}) == "M · 312 LP"
    assert rs.rank_label(None) == ""


def test_account_summary_solo_flex_and_flags():
    entries = [
        {"queueType": "RANKED_SOLO_5x5", "tier": "DIAMOND", "rank": "IV",
         "leaguePoints": 11, "wins": 61, "losses": 39, "hotStreak": True},
        {"queueType": "RANKED_FLEX_SR", "tier": "PLATINUM", "rank": "I",
         "leaguePoints": 8, "wins": 5, "losses": 5, "freshBlood": True},
    ]
    acc = rs.account_summary(entries, mastery=[{"championId": 64,
                             "championPoints": 120000, "championLevel": 7}])
    assert acc["rank"] == "D4 · 11 LP"
    assert acc["solo"]["wins"] == 61 and acc["solo"]["losses"] == 39
    assert acc["solo"]["win_rate"] == round(61 / 100, 3)
    assert acc["solo"]["hot_streak"] is True
    assert acc["flex"]["label"] == "P1 · 8 LP"
    assert acc["flex"]["fresh_blood"] is True
    assert acc["mastery"][0]["champion_id"] == 64


def test_account_summary_empty_safe():
    acc = rs.account_summary(None)
    assert acc["rank"] == ""
    assert acc["solo"] is None and acc["flex"] is None
    assert acc["mastery"] == []


# ----------------------------------------------------------- current champ
def _fp(pool):
    fp = PlayerFingerprint()
    fp.champion_pool = pool
    return fp


def test_current_champ_stats_from_pool():
    fp = _fp([{"champion_id": 64, "games": 10, "win_rate": 0.6,
               "mastery_points": 50000, "mastery_level": 7}])
    cc = rs.current_champ_stats(fp, [], 64)
    assert cc == {"games": 10, "win_rate": 0.6,
                  "mastery_points": 50000, "mastery_level": 7}


def test_current_champ_stats_mastery_fallback_when_outside_pool():
    fp = _fp([{"champion_id": 64, "games": 10, "win_rate": 0.6}])
    cc = rs.current_champ_stats(
        fp, [{"champion_id": 99, "mastery_points": 1000, "mastery_level": 3}], 99)
    assert cc["games"] is None and cc["win_rate"] is None
    assert cc["mastery_points"] == 1000 and cc["mastery_level"] == 3


def test_current_champ_stats_no_champ_or_no_fp():
    assert rs.current_champ_stats(None, None, 0) == {
        "games": None, "win_rate": None, "mastery_points": None, "mastery_level": None}
    assert rs.current_champ_stats(None, [], 64)["games"] is None


# ----------------------------------------------------------- premade detect
def _cm(*matches):
    """Build a comatches dict: each arg is (gameId, {puuid: teamId})."""
    return {gid: teammap for gid, teammap in matches}


def test_detect_premades_duo_over_threshold():
    # A & B share 3 same-team games; C/D/E never co-team → one duo.
    shared = [("g1", {"A": 100, "B": 100, "C": 200}),
              ("g2", {"A": 100, "B": 100}),
              ("g3", {"A": 100, "B": 100})]
    comatches = {"A": _cm(*shared), "B": _cm(*shared),
                 "C": {}, "D": {}, "E": {}}
    groups = rs.detect_premades({"A", "B", "C", "D", "E"}, comatches)
    assert groups == [["A", "B"]]


def test_detect_premades_threshold_not_met():
    # Only one shared game → below the default threshold of 2.
    comatches = {"A": _cm(("g1", {"A": 100, "B": 100})),
                 "B": _cm(("g1", {"A": 100, "B": 100}))}
    assert rs.detect_premades({"A", "B"}, comatches) == []


def test_detect_premades_opposite_teams_are_not_premade():
    # A and B were on OPPOSITE teams in every shared game → not premade.
    games = [("g1", {"A": 100, "B": 200}), ("g2", {"A": 100, "B": 200}),
             ("g3", {"A": 100, "B": 200})]
    comatches = {"A": _cm(*games), "B": _cm(*games)}
    assert rs.detect_premades({"A", "B"}, comatches) == []


def test_detect_premades_trio_transitive():
    # A-B linked and B-C linked (A and C never directly) → one trio.
    ab = [("g1", {"A": 100, "B": 100}), ("g2", {"A": 100, "B": 100})]
    bc = [("g3", {"B": 100, "C": 100}), ("g4", {"B": 100, "C": 100})]
    comatches = {"A": _cm(*ab), "B": _cm(*(ab + bc)), "C": _cm(*bc)}
    groups = rs.detect_premades({"A", "B", "C"}, comatches)
    assert groups == [["A", "B", "C"]]


def test_detect_premades_dedups_shared_game_id():
    # The same game id appears in both A's and B's history; it must count once,
    # so a single real shared game stays below the threshold of 2.
    g = ("g1", {"A": 100, "B": 100})
    comatches = {"A": _cm(g), "B": _cm(g)}
    assert rs.detect_premades({"A", "B"}, comatches) == []


def test_detect_premades_ignores_puuids_outside_roster():
    # F is not in the current game; A-F co-team games must not create a group.
    af = [("g1", {"A": 100, "F": 100}), ("g2", {"A": 100, "F": 100})]
    comatches = {"A": _cm(*af)}
    assert rs.detect_premades({"A", "B"}, comatches) == []


# ----------------------------------------------- scout_puuid (monkeypatched)
def test_scout_puuid_filters_sr_queues_and_returns_comatches(monkeypatch):
    monkeypatch.setattr("sylqon.config.RIOT_API_KEY", "test-key")
    monkeypatch.setattr(api, "get_ranked_stats", lambda pu: [
        {"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "II",
         "leaguePoints": 50, "wins": 10, "losses": 5, "hotStreak": True}])
    monkeypatch.setattr(api, "get_top_mastery", lambda pu, n=5: [
        {"championId": 64, "championPoints": 120000, "championLevel": 7}])
    monkeypatch.setattr(api, "get_match_ids",
                        lambda pu, count=None, queue=None: ["M1", "M2"])

    def fake_match(mid):
        if mid == "M1":  # Normal Draft (queue 400) — must be counted
            return {"info": {"gameId": 1, "queueId": 400, "gameDuration": 1800,
                    "gameCreation": 100, "participants": [
                        {"puuid": "P", "championId": 64, "win": True, "teamId": 100,
                         "totalMinionsKilled": 180, "neutralMinionsKilled": 0,
                         "kills": 5, "deaths": 3, "assists": 7,
                         "teamPosition": "JUNGLE", "totalDamageTaken": 10000,
                         "visionScore": 20},
                        {"puuid": "Q", "championId": 1, "teamId": 100},
                        {"puuid": "R", "championId": 2, "teamId": 200}]}}
        return {"info": {"gameId": 2, "queueId": 450,  # ARAM — must be skipped
                "participants": [{"puuid": "P", "championId": 64, "teamId": 100}]}}

    monkeypatch.setattr(api, "get_match", fake_match)

    fp, account, comatches = rs.scout_puuid("P")
    # Only the Normal Draft (SR) game is counted; ARAM is filtered out.
    assert fp.games_analyzed == 1
    assert "1" in comatches and "2" not in comatches
    assert comatches["1"] == {"P": 100, "Q": 100, "R": 200}
    assert account["solo"]["hot_streak"] is True
    assert account["solo"]["win_rate"] == round(10 / 15, 3)
    assert account["rank"].startswith("G2")
    # current-champ mastery resolves from the top-mastery list for champ 64.
    cc = rs.current_champ_stats(fp, account["mastery"], 64)
    assert cc["games"] == 1 and cc["mastery_points"] == 120000


def test_scout_puuid_no_api_key_is_empty(monkeypatch):
    monkeypatch.setattr("sylqon.config.RIOT_API_KEY", "")
    fp, account, comatches = rs.scout_puuid("P")
    assert fp.games_analyzed == 0 and comatches == {} and account["rank"] == ""

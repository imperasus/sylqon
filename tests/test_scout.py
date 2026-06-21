"""Offline tests for pre-game lobby scouting.

Cover the playstyle-fingerprint heuristics, the puuid match-history fetch (path
selection + gameId dedup), and the prompt scout-block formatting — all without a
League client, Ollama, or the network.

Run: python -m pytest tests/test_scout.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.ai.pick_prompt import format_scout_block
from sylqon.lcu import scout as scout_mod
from sylqon.lcu.scout import PlayerFingerprint, fingerprint


def mk(cid, role, win, k, d, a, cspm=6.0, played_at=0):
    return {
        "game_id": str(played_at), "champion_id": cid, "role": role,
        "result": "Win" if win else "Loss",
        "kda": {"kills": k, "deaths": d, "assists": a},
        "stats": {"cs_per_min": cspm}, "timeline": [], "played_at": played_at,
    }


def test_empty_input_yields_empty_fingerprint():
    fp = fingerprint([])
    assert fp == PlayerFingerprint()
    assert fp.games_analyzed == 0
    assert fp.comfort is None
    assert fp.playstyle_tags == []


def test_main_role_and_pool_ordering():
    games = ([mk(64, "jungle", True, 5, 4, 8) for _ in range(6)]
             + [mk(121, "jungle", False, 3, 5, 6) for _ in range(2)]
             + [mk(0, "middle", True, 4, 4, 4)])  # one off-role game
    fp = fingerprint(games)
    assert fp.games_analyzed == 9
    assert fp.main_role == "jungle"
    # Most-played champion first; win_rate computed per champion.
    assert fp.champion_pool[0]["champion_id"] == 64
    assert fp.champion_pool[0]["games"] == 6
    assert fp.champion_pool[0]["win_rate"] == 1.0


def test_one_trick_and_comfort_share():
    games = [mk(64, "jungle", True, 5, 4, 6) for _ in range(8)] + \
            [mk(11, "jungle", False, 2, 6, 3) for _ in range(2)]
    fp = fingerprint(games)
    assert fp.comfort["champion_id"] == 64
    assert fp.comfort["share"] == 0.8
    assert "one-trick" in fp.playstyle_tags


def test_aggressive_tag_on_high_kills_and_deaths():
    games = [mk(157, "top", True, 8, 8, 5) for _ in range(10)]
    fp = fingerprint(games)
    assert "aggressive" in fp.playstyle_tags


def test_farm_focused_and_calculated_tags():
    # Low deaths, strong KDA, high CS → calculated + farm-focused, not aggressive.
    games = [mk(202, "bottom", True, 7, 2, 6, cspm=8.5) for _ in range(10)]
    fp = fingerprint(games)
    assert "farm-focused" in fp.playstyle_tags
    assert "calculated" in fp.playstyle_tags
    assert "aggressive" not in fp.playstyle_tags


def test_recent_form_win_and_loss_streaks():
    # Newest-first: 4 wins then losses → +4 streak, win_rate over window.
    wins = [mk(1, "top", True, 1, 1, 1, played_at=i) for i in range(4)]
    losses = [mk(1, "top", False, 1, 1, 1, played_at=10 + i) for i in range(3)]
    fp = fingerprint(wins + losses)
    assert fp.recent_form["games"] == 7
    assert fp.recent_form["streak"] == 4
    # Leading with a loss yields a negative streak.
    fp2 = fingerprint(losses + wins)
    assert fp2.recent_form["streak"] == -3


# ---------------------------------------------------------- history fetch
class FakeClient:
    """Returns a single fixed page regardless of begIndex/endIndex (mirrors the
    LCU bug the dedup guards against) and records the path it was asked for."""

    def __init__(self, games):
        self._games = games
        self.paths: list[str] = []

    def get_json(self, path):
        self.paths.append(path)
        return {"games": {"games": self._games}}


def test_recent_games_for_puuid_uses_puuid_path_and_dedups():
    raw = [
        {"gameId": 1, "queueId": 420, "gameDuration": 1800, "gameCreation": 100,
         "participants": [{"championId": 64, "stats": {"win": True, "kills": 5,
                          "deaths": 4, "assists": 8, "totalMinionsKilled": 200,
                          "neutralMinionsKilled": 20}, "timeline": {"lane": "JUNGLE"}}]},
        {"gameId": 2, "queueId": 450, "gameDuration": 1200, "gameCreation": 200,
         "participants": [{"championId": 1, "stats": {"win": False}}]},  # ARAM, filtered
    ]
    client = FakeClient(raw)
    games = scout_mod.recent_games_for_puuid(client, "PUUID-XYZ", count=40)
    # Only the SR game survives, deduped to a single entry despite repeated pages.
    assert len(games) == 1
    assert games[0]["champion_id"] == 64
    assert any("PUUID-XYZ" in p for p in client.paths)


def test_recent_games_for_puuid_empty_without_puuid():
    assert scout_mod.recent_games_for_puuid(FakeClient([]), "") == []


# ---------------------------------------------------- local rank from the LCU
class RankedClient:
    """Returns a fixed /lol-ranked/v1/current-ranked-stats payload."""

    def __init__(self, data):
        self._data = data

    def get_json(self, path):
        return self._data


def test_current_ranked_summary_solo_and_flex():
    from sylqon.lcu.ranked import current_ranked_summary
    data = {"queueMap": {
        "RANKED_SOLO_5x5": {"tier": "GOLD", "division": "I", "leaguePoints": 82,
                            "wins": 50, "losses": 40, "isHotStreak": True},
        "RANKED_FLEX_SR": {"tier": "NONE", "division": "NA"},  # unranked → dropped
    }}
    acc = current_ranked_summary(RankedClient(data))
    assert acc["rank"] == "G1 · 82 LP"
    assert acc["solo"]["win_rate"] == round(50 / 90, 3)
    assert acc["solo"]["hot_streak"] is True
    assert acc["flex"] is None


def test_current_ranked_summary_apex_blank_division():
    from sylqon.lcu.ranked import current_ranked_summary
    data = {"queueMap": {"RANKED_SOLO_5x5": {"tier": "MASTER", "division": "NA",
                         "leaguePoints": 312, "wins": 0, "losses": 0}}}
    acc = current_ranked_summary(RankedClient(data))
    assert acc["rank"] == "M · 312 LP"
    assert acc["solo"]["win_rate"] is None   # 0 games


def test_current_ranked_summary_unranked_and_bad_input():
    from sylqon.lcu.ranked import current_ranked_summary
    assert current_ranked_summary(
        RankedClient({"queueMap": {"RANKED_SOLO_5x5": {"tier": "NONE"}}})) is None
    assert current_ranked_summary(RankedClient(None)) is None


# ------------------------------------------------------- prompt scout block
def test_scout_block_omitted_without_usable_players():
    assert format_scout_block(None) == ""
    assert format_scout_block([]) == ""
    # Only self + hidden + zero-game players → nothing to show.
    players = [
        {"name": "Me", "is_self": True, "games_analyzed": 20},
        {"name": "Anon", "hidden": True},
        {"name": "NoData", "games_analyzed": 0},
    ]
    assert format_scout_block(players) == ""


def test_scout_block_renders_teammate_line():
    players = [{
        "name": "Faker", "position": "middle", "games_analyzed": 15,
        "playstyle_tags": ["carry-threat", "one-trick"],
        "comfort": {"champion": "Azir", "share": 0.6},
        "recent_form": {"games": 10, "wins": 8, "win_rate": 0.8, "streak": 4},
    }]
    block = format_scout_block(players)
    assert "TEAMMATE SCOUT" in block
    assert "Faker" in block
    assert "Azir" in block
    assert "carry-threat" in block
    assert "4W streak" in block


def test_scout_block_renders_loss_streak():
    """A negative streak (>= 3 losses) must appear as 'L streak', not 'W'."""
    players = [{
        "name": "Unlucky", "position": "top", "games_analyzed": 12,
        "recent_form": {"games": 12, "wins": 3, "win_rate": 0.25, "streak": -5},
    }]
    block = format_scout_block(players)
    assert "5L streak" in block
    assert "W streak" not in block


def test_scout_block_no_streak_label_when_below_threshold():
    """Streaks of -2, -1, 0, 1, 2 must NOT add a streak label to the line."""
    for streak in (-2, -1, 0, 1, 2):
        players = [{
            "name": "Player", "position": "jungle", "games_analyzed": 5,
            "recent_form": {"games": 5, "wins": 2, "win_rate": 0.4,
                            "streak": streak},
        }]
        block = format_scout_block(players)
        assert "streak" not in block, f"unexpected streak label for streak={streak}"


def test_scout_block_position_fallback_to_main_role_then_flex():
    """When 'position' is absent, fall back to 'main_role'; when both absent use 'flex'."""
    p_main = {
        "name": "Player", "games_analyzed": 5, "main_role": "jungle",
    }
    p_flex = {
        "name": "Player2", "games_analyzed": 5,
    }
    block_main = format_scout_block([p_main])
    assert "jungle Player" in block_main

    block_flex = format_scout_block([p_flex])
    assert "flex Player2" in block_flex


def test_scout_block_excludes_self_even_with_games():
    """is_self=True players must always be excluded, even when games_analyzed > 0."""
    players = [{
        "name": "Me", "position": "bottom", "games_analyzed": 20,
        "is_self": True,
        "recent_form": {"games": 20, "wins": 15, "win_rate": 0.75, "streak": 5},
    }]
    assert format_scout_block(players) == ""


def test_scout_block_mixed_self_and_teammate():
    """Only the teammate line should appear when mixed with self+hidden."""
    players = [
        {"name": "Me", "position": "bottom", "is_self": True, "games_analyzed": 20},
        {"name": "Anon", "hidden": True},
        {"name": "Ally", "position": "top", "games_analyzed": 8,
         "playstyle_tags": ["aggressive"]},
    ]
    block = format_scout_block(players)
    assert "TEAMMATE SCOUT" in block
    assert "Ally" in block
    assert "Me" not in block
    assert "Anon" not in block


def test_scout_block_comfort_without_champion_name_omitted():
    """If comfort has no 'champion' key (id-only, not yet enriched), skip it."""
    players = [{
        "name": "Player", "position": "mid", "games_analyzed": 5,
        "comfort": {"champion_id": 64, "share": 0.8},  # no 'champion' key
    }]
    block = format_scout_block(players)
    # The block renders (games_analyzed > 0) but no 'mains ...' text appears.
    assert "TEAMMATE SCOUT" in block
    assert "mains" not in block


# ------------------------------------------------- role-aware thresholds
def mkfull(cid, role, win, k, d, a, cspm=6.0, dtaken=0, vision=0, dur=1800):
    g = mk(cid, role, win, k, d, a, cspm)
    g["stats"].update({"duration": dur, "damage_taken": dtaken, "vision_score": vision})
    return g


def test_support_is_not_mislabeled_by_flat_thresholds():
    # A roaming engage support: low kills/CS by design, high assists.
    games = [mkfull(412, "utility", True, 3, 7, 13, cspm=1.0, vision=50) for _ in range(10)]
    fp = fingerprint(games)
    # 3 kills clears the support aggro floor (2.5) with high deaths → aggressive.
    assert "aggressive" in fp.playstyle_tags
    assert "playmaker" in fp.playstyle_tags
    # Supports are excluded from the farm tag regardless of (low) CS.
    assert "farm-focused" not in fp.playstyle_tags
    # High vision score → macro/vision-control read.
    assert "vision-control" in fp.playstyle_tags


def test_jungle_kill_floor_is_lower_than_mid():
    # 5.2 avg kills: above the jungle floor (5.0) but below mid's (6.0).
    jg = fingerprint([mkfull(64, "jungle", True, 5, 7, 6) for _ in range(5)]
                     + [mkfull(64, "jungle", True, 6, 7, 6) for _ in range(5)])
    md = fingerprint([mkfull(103, "middle", True, 5, 7, 6) for _ in range(5)]
                     + [mkfull(103, "middle", True, 6, 7, 6) for _ in range(5)])
    assert "aggressive" in jg.playstyle_tags
    assert "aggressive" not in md.playstyle_tags


def test_frontliner_tag_from_damage_taken():
    # ~2000 dmg taken/min over 30-min games → frontliner.
    games = [mkfull(54, "top", True, 3, 5, 7, dtaken=60000, dur=1800) for _ in range(10)]
    fp = fingerprint(games)
    assert fp.avg_damage_taken_per_min == 2000  # 60000 over 30 min
    assert "frontliner" in fp.playstyle_tags


def test_fed_carry_keeps_high_aggression_despite_high_farm():
    # High kills + high CS must NOT read as passive: the farm penalty is gated
    # on low involvement, so a fed, farming carry stays aggressive.
    games = [mkfull(202, "bottom", True, 8, 3, 7, cspm=9.0) for _ in range(10)]
    fp = fingerprint(games)
    assert fp.aggression >= 0.5
    assert "carry-threat" in fp.playstyle_tags

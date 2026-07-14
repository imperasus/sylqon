"""Offline tests for the Daily Draft puzzle generator (app/puzzles.py).

Seeds well-formed 5v5 Match-V5 bundles with real champion slugs (so the draft
bundle resolves every pick), then exercises selection, freezing, candidate
analysis, anonymity and the get-or-create/replace lifecycle.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from app import draftintel, puzzles, store
from app.models import PlayerRank

DATE = "2026-07-20"
ROLE = puzzles._role_for(DATE)  # rotates by calendar day; resolve once

# Four disjoint drafts (all single-word slugs == display names) so every role
# has eight distinct fallback candidates across the dataset.
TEAMS = [
    (["Malphite", "Amumu", "Ahri", "Jinx", "Leona"],
     ["Fiora", "Sejuani", "Xerath", "Caitlyn", "Thresh"]),
    (["Garen", "Vi", "Orianna", "Ashe", "Braum"],
     ["Darius", "Nocturne", "Syndra", "Draven", "Nautilus"]),
    (["Jax", "Skarner", "Zoe", "Sivir", "Soraka"],
     ["Riven", "Rammus", "Veigar", "Ezreal", "Lulu"]),
    (["Ornn", "Zac", "Annie", "Vayne", "Pyke"],
     ["Camille", "Trundle", "Lux", "Tristana", "Alistar"]),
]


def _participant(i, puuid, champ_name, team, win):
    return {
        "puuid": puuid, "participantId": i, "teamId": team,
        "championId": 1000 + i, "championName": champ_name,
        "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][(i - 1) % 5],
        "win": win, "kills": 4, "deaths": 1, "assists": 9,
        "goldEarned": 13000, "totalMinionsKilled": 200, "neutralMinionsKilled": 12,
        "visionScore": 30, "wardsPlaced": 10, "visionWardsBoughtInGame": 2,
        "totalDamageDealtToChampions": 25000,
        "item0": 3153, "item1": 3006, "item2": 0, "item3": 3036,
    }


def _match(match_id, created, blue, red, blue_win=True, duration=1800):
    parts = []
    for i, name in enumerate(blue + red, start=1):
        team = 100 if i <= 5 else 200
        win = blue_win if team == 100 else not blue_win
        parts.append(_participant(i, f"p-{match_id}-{i}", name, team, win))
    return {
        "metadata": {"matchId": match_id},
        "info": {"queueId": 420, "gameCreation": created, "gameDuration": duration,
                 "gameVersion": "16.13.1.1", "participants": parts},
    }


def _seed_default(factory):
    with factory() as s:
        for n, (blue, red) in enumerate(TEAMS):
            store.insert_match_bundle(
                s, _match(f"EUN1_{n}", 1000 + n, blue, red, blue_win=(n % 2 == 0)),
                {"info": {}}, region="europe")


def test_generates_wellformed_anonymous_payload(factory):
    _seed_default(factory)
    with factory() as s:
        payload, created = puzzles.generate_for_date(s, DATE)
    assert created is True
    assert payload["schema"] == puzzles.PUZZLE_SCHEMA
    assert payload["role"] == ROLE
    assert len(payload["ally"]) == 4 and len(payload["enemy"]) == 5

    cands = payload["candidates"]
    assert len(cands) == puzzles.CANDIDATE_COUNT
    assert len({c["name"] for c in cands}) == puzzles.CANDIDATE_COUNT
    assert sum(c["is_real"] for c in cands) == 1
    assert sum(c["is_engine_top"] for c in cands) == 1

    revealed = {c["name"] for c in payload["ally"]} | {c["name"] for c in payload["enemy"]}
    real = next(c for c in cands if c["is_real"])
    assert real["name"] not in revealed  # the hidden pick stays hidden
    assert real["name"] == payload["epilogue"]["name"]

    for c in cands:
        assert 35 <= c["balance"]["win_pct"] <= 65  # ToS band survives folding
        assert c["tier"] in {"strong", "solid", "risky"}
        assert c["slug"]  # DDragon id for the icon URL

    # Anonymity: champions only — no player identity anywhere in the payload.
    dumped = json.dumps(payload)
    assert "puuid" not in dumped and "p-EUN1_" not in dumped
    assert "match_id" not in dumped and "EUN1_" not in dumped


def test_get_or_create_is_idempotent(factory):
    _seed_default(factory)
    with factory() as s:
        first, created = puzzles.generate_for_date(s, DATE)
        second, created_again = puzzles.generate_for_date(s, DATE)
    assert created is True and created_again is False
    assert first == second
    with factory() as s:
        assert puzzles.get_puzzle(s, DATE) == first
        assert puzzles.get_puzzle(s, "1999-01-01") is None


def test_build_is_deterministic_per_date(factory):
    _seed_default(factory)
    with factory() as s:
        assert puzzles.build_puzzle(s, DATE) == puzzles.build_puzzle(s, DATE)


def test_replace_freezes_a_different_match(factory):
    _seed_default(factory)
    with factory() as s:
        puzzles.generate_for_date(s, DATE)
        old = s.get(puzzles.DailyPuzzle, DATE).match_id
        _, changed = puzzles.generate_for_date(s, DATE, replace=True)
        new = s.get(puzzles.DailyPuzzle, DATE).match_id
    assert changed is True
    assert new != old  # curation contract: --replace never re-serves the same match


def test_cross_day_matches_never_repeat(factory):
    _seed_default(factory)
    days = [(date.fromisoformat(DATE).toordinal() + i) for i in range(3)]
    isos = [date.fromordinal(d).isoformat() for d in days]
    with factory() as s:
        for iso in isos:
            puzzles.generate_for_date(s, iso)
        used = [s.get(puzzles.DailyPuzzle, iso).match_id for iso in isos]
    assert len(set(used)) == len(used)


def test_epilogue_reflects_the_hidden_participant(factory):
    _seed_default(factory)
    with factory() as s:
        payload, _ = puzzles.generate_for_date(s, DATE)
    epi = payload["epilogue"]
    assert (epi["kills"], epi["deaths"], epi["assists"]) == (4, 1, 9)
    assert epi["cs"] == 212  # 200 minions + 12 neutral
    assert epi["items"] == [3153, 3006, 3036]  # zero slots dropped
    assert isinstance(epi["win"], bool)


def test_rank_band_is_highest_known_tier(factory):
    _seed_default(factory)
    with factory() as s:
        s.add(PlayerRank(puuid="p-EUN1_0-3", platform="eun1", tier="GOLD"))
        s.add(PlayerRank(puuid="p-EUN1_0-8", platform="eun1", tier="EMERALD"))
        s.add(PlayerRank(puuid="p-EUN1_1-2", platform="eun1", tier="DIAMOND"))
        s.commit()
        bands = {puzzles.generate_for_date(s, iso)[0]["match"]["rank_band"]
                 for iso in (DATE, "2026-07-21", "2026-07-22", "2026-07-23")}
    # every seeded match is frozen across the four days: the two rank-tagged
    # matches must surface their highest tier, the untagged ones None
    assert "EMERALD" in bands or "DIAMOND" in bands
    assert None in bands


def test_skips_malformed_and_short_matches(factory):
    with factory() as s:
        # nine participants (parser drops one) → not well-formed
        broken = _match("EUN1_BAD", 1000, *TEAMS[0])
        broken["info"]["participants"] = broken["info"]["participants"][:9]
        store.insert_match_bundle(s, broken, {"info": {}}, region="europe")
        # long enough dataset-wise but a remake-length game → duration floor
        store.insert_match_bundle(
            s, _match("EUN1_SHORT", 1001, *TEAMS[1], duration=300),
            {"info": {}}, region="europe")
        with pytest.raises(puzzles.PuzzleNotPossible):
            puzzles.build_puzzle(s, DATE)


def test_lane_record_folds_into_the_engine_read():
    """The (wr - 50) * 0.2 lane mapping must surface as a Lane driver."""
    ally = ["Amumu", "Sejuani", "Alistar", "Jinx"]
    enemy = ["Fiora", "Nocturne", "Syndra", "Draven", "Nautilus"]
    ahead = puzzles._analyze("Malphite", ally, enemy, lane=(10, 65))
    behind = puzzles._analyze("Malphite", ally, enemy, lane=(10, 35))
    flat = puzzles._analyze("Malphite", ally, enemy, lane=None)
    texts_ahead = [d["text"] for d in ahead["balance"]["drivers"]]
    texts_behind = [d["text"] for d in behind["balance"]["drivers"]]
    assert "Lane lead" in texts_ahead
    assert "Lane deficit" in texts_behind
    assert ahead["balance"]["win_pct"] >= flat["balance"]["win_pct"] \
        >= behind["balance"]["win_pct"]


def test_identity_resolves_slug_and_display_spellings():
    assert draftintel.identity("DrMundo") == draftintel.identity("Dr. Mundo")
    assert draftintel.identity("MonkeyKing")["name"] == "Wukong"
    assert draftintel.identity("Nunu & Willump")["slug"] == "Nunu"
    assert draftintel.identity("Notachamp") is None

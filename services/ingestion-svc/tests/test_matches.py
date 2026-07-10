"""Offline tests for the stored-match read views (list + detail)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import matches, store
from app.models import Base

ME = "puuid-me"


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _participant(i, puuid, champ_id, champ_name, team, win):
    return {
        "puuid": puuid, "participantId": i, "teamId": team,
        "championId": champ_id, "championName": champ_name,
        "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][(i - 1) % 5],
        "win": win, "kills": 3, "deaths": 2, "assists": 7,
        "goldEarned": 12000, "totalMinionsKilled": 180, "neutralMinionsKilled": 10,
        "visionScore": 25, "wardsPlaced": 12, "visionWardsBoughtInGame": 3,
        "totalDamageDealtToChampions": 20000,
        "item0": 3153, "item1": 3006, "item6": 3340,
    }


def _match(match_id, created, me_puuid, me_win=True):
    parts = []
    for i in range(1, 11):
        team = 100 if i <= 5 else 200
        win = me_win if team == 100 else not me_win
        if i == 1:
            parts.append(_participant(i, me_puuid, 266, "Aatrox", team, win))
        else:
            parts.append(_participant(i, f"f-{match_id}-{i}", 100 + i, f"Champ{i}", team, win))
    return {
        "metadata": {"matchId": match_id},
        "info": {"queueId": 420, "gameCreation": created, "gameDuration": 1800,
                 "gameVersion": "16.13.1.1", "participants": parts},
    }


def _seed(factory, *specs):
    with factory() as s:
        for match_id, created, win in specs:
            store.insert_match_bundle(s, _match(match_id, created, ME, win),
                                      {"info": {}}, region="europe")


def test_list_for_puuid_newest_first(factory):
    _seed(factory, ("EUN1_1", 1000, True), ("EUN1_2", 2000, False))
    with factory() as s:
        rows = matches.list_for_puuid(s, ME)
    assert [r["match_id"] for r in rows] == ["EUN1_2", "EUN1_1"]
    top = rows[0]
    assert top["champion"] == "Aatrox"
    assert top["win"] is False
    assert top["cs"] == 190  # 180 minions + 10 neutral
    assert top["cs_per_min"] == 6.3  # 190 / 30 min
    assert top["queue"] == "Ranked Solo/Duo"
    assert top["champion_url"].endswith("/img/champion/Aatrox.png")


def test_detail_splits_two_teams(factory):
    _seed(factory, ("EUN1_1", 1000, True))
    with factory() as s:
        d = matches.detail(s, "EUN1_1")
    assert d is not None
    assert d["queue"] == "Ranked Solo/Duo"
    blue, red = d["teams"]
    assert blue["team_id"] == 100 and blue["win"] is True
    assert red["team_id"] == 200 and red["win"] is False
    assert len(blue["participants"]) == 5
    assert blue["kills"] == 15  # 5 players × 3 kills
    p = blue["participants"][0]
    assert p["champion"] == "Aatrox"
    assert p["cs"] == 190
    assert len(p["items"]) == 3  # item0/1/6 non-zero → three icon URLs


def test_detail_none_for_unknown_match(factory):
    with factory() as s:
        assert matches.detail(s, "NOPE_1") is None


def _frames(diffs):
    """Per-minute frames where blue-team gold leads red by the given amounts."""
    frames = []
    for i, d in enumerate(diffs):
        pf = {str(p): {"totalGold": 1000 + (d if p == 1 else 0)} for p in range(1, 6)}
        pf.update({str(p): {"totalGold": 1000} for p in range(6, 11)})
        frames.append({"timestamp": i * 60000, "participantFrames": pf})
    return frames


def test_gold_timeline_computes_team_diffs(factory):
    with factory() as s:
        store.insert_match_bundle(s, _match("EUN1_1", 1000, ME, True),
                                  {"info": {"frames": _frames([0, 500, -300])}},
                                  region="europe")
        points = matches.gold_timeline(s, "EUN1_1")
    assert [p["diff"] for p in points] == [0, 500, -300]
    assert [p["minute"] for p in points] == [0.0, 1.0, 2.0]


def test_gold_timeline_none_without_frames(factory):
    _seed(factory, ("EUN1_1", 1000, True))  # seeded with an empty timeline
    with factory() as s:
        assert matches.gold_timeline(s, "EUN1_1") is None

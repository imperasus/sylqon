"""Offline tests for the pool-coverage analysis (synthetic controlled dataset)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import pool, store
from app.models import Base

ME = "puuid-me"


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def lane_match(match_id, champ_a, champ_b, a_wins, *, role="BOTTOM", a_puuid="pa"):
    """One SR match whose only meaningful lane is `role`: champ_a vs champ_b."""
    participants = []
    roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    for i in range(10):
        r = roles[i % 5]
        team = 100 if i < 5 else 200
        name = f"Filler{r}{team}"
        puuid = f"filler-{match_id}-{i}"
        if r == role:
            if team == 100:
                name, puuid = champ_a, a_puuid
            else:
                name, puuid = champ_b, f"opp-{match_id}"
        participants.append(
            {
                "puuid": puuid,
                "participantId": i + 1,
                "teamId": team,
                "championName": name,
                "teamPosition": r,
                "win": (team == 100) == a_wins,
                "kills": 1, "deaths": 1, "assists": 1,
                "wardsPlaced": 5, "visionWardsBoughtInGame": 1,
            }
        )
    return {
        "metadata": {"matchId": match_id},
        "info": {
            "queueId": 420,
            "gameDuration": 1800,
            "gameVersion": "16.13.1.1",
            "participants": participants,
        },
    }


def seed(session_factory, specs):
    """specs: list of (champ_a, champ_b, a_wins, a_puuid)."""
    with session_factory() as s:
        for i, (a, b, win, puuid) in enumerate(specs):
            m = lane_match(f"EUN1_{i}", a, b, win, a_puuid=puuid)
            store.insert_match_bundle(s, m, {"info": {"frames": []}}, region="europe")


def test_role_dataset_counts_matchups(session_factory):
    seed(session_factory, [
        ("Jinx", "Caitlyn", True, ME),
        ("Jinx", "Caitlyn", True, ME),
        ("Jinx", "Draven", False, ME),
    ])
    with session_factory() as s:
        data = pool.role_dataset(s, "BOTTOM")
    assert data["champs"]["Jinx"] == [3, 2]
    assert data["matchups"][("Jinx", "Caitlyn")] == [2, 2]
    assert data["matchups"][("Caitlyn", "Jinx")] == [2, 0]
    assert data["matchups"][("Jinx", "Draven")] == [1, 0]


def test_analyze_pool_full_report(session_factory):
    # Me on Jinx: beats Caitlyn twice, loses to Draven twice; enemies exist as threats.
    seed(session_factory, [
        ("Jinx", "Caitlyn", True, ME),
        ("Jinx", "Caitlyn", True, ME),
        ("Jinx", "Draven", False, ME),
        ("Jinx", "Draven", False, ME),
        ("Caitlyn", "Draven", True, "other-1"),
        ("Caitlyn", "Draven", True, "other-1"),
        ("Caitlyn", "Draven", True, "other-1"),
    ])
    with session_factory() as s:
        report = pool.analyze_pool(s, ME)
    assert report is not None
    bot = report["roles"]["BOTTOM"]
    assert bot["games"] == 4
    assert bot["current"][0]["champion"] == "Jinx"
    # Draven is a judged threat and Jinx loses to him → uncovered
    assert "Draven" in bot["uncovered"]
    comps = bot["components"]
    assert comps["counter_coverage"] == 50  # 2 judged threats, 1 covered
    # Jinx's worst matchup (0% vs Draven) drags blind safety down
    assert comps["blind_safety"] == 0
    assert 0 <= bot["coverage_score"] <= 100
    # Suggestion should reach for Caitlyn (beats Draven 3/3 in dataset)
    suggested = [c["champion"] for c in bot["suggested"]]
    assert "Caitlyn" in suggested


def test_honesty_gate_on_thin_data(session_factory):
    seed(session_factory, [("Jinx", "Caitlyn", True, ME)])  # single game
    with session_factory() as s:
        report = pool.analyze_pool(s, ME)
    bot = report["roles"]["BOTTOM"]
    assert bot["low_data"] is True
    # single game: matchup below MIN_MATCHUP_GAMES → neutral blind safety
    assert bot["components"]["blind_safety"] == 50


def test_unknown_player_returns_none(session_factory):
    seed(session_factory, [("Jinx", "Caitlyn", True, "someone")])
    with session_factory() as s:
        assert pool.analyze_pool(s, "puuid-ghost") is None


def test_shrunk_wr_regresses_small_samples():
    assert pool._shrunk_wr(2, 2) < 80          # 2/2 is not 100%
    assert pool._shrunk_wr(20, 10) == pytest.approx(50, abs=2)
    assert pool._shrunk_wr(0, 0) == 50


def test_suggested_pool_size_and_reasons(session_factory):
    specs = []
    # Me: strong on Jinx (4W/1L)
    for i in range(4):
        specs.append(("Jinx", "Caitlyn", True, ME))
    specs.append(("Jinx", "Draven", False, ME))
    # Dataset: Caitlyn and Ashe present enough to be candidates
    for i in range(3):
        specs.append(("Caitlyn", "Draven", True, "o1"))
        specs.append(("Ashe", "Draven", True, "o2"))
    seed(session_factory, specs)
    with session_factory() as s:
        report = pool.analyze_pool(s, ME)
    suggested = report["roles"]["BOTTOM"]["suggested"]
    assert len(suggested) == pool.POOL_SIZE
    jinx = next(c for c in suggested if c["champion"] == "Jinx")
    assert "comfort" in jinx["reasons"]
    assert jinx["personal"] == {"games": 5, "wins": 4}

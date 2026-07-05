"""Offline tests for own-data builds/matchups and the bot's DB-side logic."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import builds, store
from app.advice import benchmarks
from app.models import AdviceFeedback, Base, LinkedAccount

from tests.test_store_crawler import make_match, make_riot, make_timeline
from tests.test_watcher import make_watcher

CORE = sorted(benchmarks.CORE_ITEM_IDS)[:3]


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def store_match_with_champs(session_factory, match_id, *, jinx_win=True):
    """participant 1 = Jinx (BOTTOM, team 100), participant 6 = Ashe (BOTTOM, team 200)."""
    match = make_match(match_id)
    parts = match["info"]["participants"]
    for i, p in enumerate(parts):
        p["teamPosition"] = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][i % 5]
        p["win"] = (i < 5) == jinx_win
    parts[3]["championName"] = "Jinx"      # team 100 BOTTOM
    parts[8]["championName"] = "Ashe"      # team 200 BOTTOM
    for slot, item in enumerate(CORE):
        parts[3][f"item{slot}"] = item
    with session_factory() as s:
        store.insert_match_bundle(s, match, make_timeline(match_id), region="europe")


def test_build_aggregation_and_min_games(session_factory):
    for i in range(3):
        store_match_with_champs(session_factory, f"EUN1_{i}", jinx_win=(i < 2))
    with session_factory() as s:
        data = builds.build_for_champion(s, "jinx")  # case-insensitive
        assert data["games"] == 3
        assert data["winrate_pct"] == 67
        assert data["role"] == "BOTTOM"
        assert [i["id"] for i in data["core_items"][:3]] == CORE
        assert builds.build_for_champion(s, "Teemo") is None  # no data


def test_matchup_same_lane_only(session_factory):
    for i in range(2):
        store_match_with_champs(session_factory, f"EUN1_m{i}", jinx_win=True)
    with session_factory() as s:
        data = builds.matchup(s, "Jinx", "Ashe")
        assert data["games"] == 2
        assert data["a_wins"] == 2
        assert data["a_winrate_pct"] == 100
        assert builds.matchup(s, "Jinx", "Champ0") is None  # different lane


def test_watcher_picks_up_linked_accounts(session_factory):
    riot = make_riot(["EUN1_1"])
    watcher, _ = make_watcher(session_factory, riot)
    with session_factory() as s:
        s.add(LinkedAccount(discord_user_id=42, puuid="puuid-linked",
                            game_name="X", tag_line="Y"))
        s.commit()
    tracked = watcher._tracked_puuids()
    assert "puuid-1" in tracked and "puuid-linked" in tracked


def test_feedback_unique_per_user(session_factory):
    with session_factory() as s:
        s.add(AdviceFeedback(match_id="EUN1_1", puuid="p", discord_user_id=42, vote=1))
        s.commit()
    with session_factory() as s:
        s.add(AdviceFeedback(match_id="EUN1_1", puuid="p", discord_user_id=42, vote=-1))
        with pytest.raises(IntegrityError):
            s.commit()
    with session_factory() as s:  # different user may vote
        s.add(AdviceFeedback(match_id="EUN1_1", puuid="p", discord_user_id=43, vote=-1))
        s.commit()

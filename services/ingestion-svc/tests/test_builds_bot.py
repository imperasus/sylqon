"""Offline tests for own-data builds/matchups and the bot's DB-side logic."""
import pytest
from app import builds, store
from app.advice import benchmarks
from app.models import AdviceFeedback, Base, LinkedAccount
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
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


def store_match_with_champs(session_factory, match_id, *, jinx_win=True, opponent="Ashe"):
    """participant 1 = Jinx (BOTTOM, team 100), participant 6 = opponent (BOTTOM, team 200)."""
    match = make_match(match_id)
    parts = match["info"]["participants"]
    for i, p in enumerate(parts):
        p["teamPosition"] = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][i % 5]
        p["win"] = (i < 5) == jinx_win
    parts[3]["championName"] = "Jinx"      # team 100 BOTTOM
    parts[8]["championName"] = opponent    # team 200 BOTTOM
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


def test_build_counts_items_per_slot(session_factory):
    """The SQL slot extraction keeps the original semantics: a completed item
    counts once per inventory slot, non-core ids and missing slots are ignored."""
    non_core = max(benchmarks.CORE_ITEM_IDS) + 1
    for i in range(3):
        match = make_match(f"EUN1_s{i}")
        jinx = match["info"]["participants"][3]
        jinx["championName"] = "Jinx"
        if i == 0:
            jinx["item0"] = CORE[0]
            jinx["item1"] = CORE[0]  # two copies in the final inventory
            jinx["item2"] = non_core
        with session_factory() as s:
            store.insert_match_bundle(s, match, make_timeline(f"EUN1_s{i}"), region="europe")
    with session_factory() as s:
        data = builds.build_for_champion(s, "Jinx")
    assert data["games"] == 3
    assert data["core_items"] == [
        {"id": CORE[0], "name": benchmarks.CORE_ITEM_NAMES[CORE[0]], "games": 2, "pct": 67}
    ]


def test_matchup_same_lane_only(session_factory):
    for i in range(2):
        store_match_with_champs(session_factory, f"EUN1_m{i}", jinx_win=True)
    with session_factory() as s:
        data = builds.matchup(s, "Jinx", "Ashe")
        assert data["games"] == 2
        assert data["a_wins"] == 2
        assert data["a_winrate_pct"] == 100
        assert builds.matchup(s, "Jinx", "Champ0") is None  # different lane


def test_champion_matchups_per_opponent(session_factory):
    for i in range(3):
        store_match_with_champs(session_factory, f"EUN1_c{i}", jinx_win=(i < 1),
                                opponent="Caitlyn")
    for i in range(2):
        store_match_with_champs(session_factory, f"EUN1_a{i}", jinx_win=True)
    store_match_with_champs(session_factory, "EUN1_d0", opponent="Draven")

    with session_factory() as s:
        rows = builds.champion_matchups(s, "jinx", "BOTTOM")  # case-insensitive
        # Most-played first; the single Draven game is honesty-gated away.
        assert rows == [("Caitlyn", 3, 33), ("Ashe", 2, 100)]
        assert builds.champion_matchups(s, "Jinx", "MIDDLE") == []

        # Exactly what the role_dataset-based champion page used to compute.
        from app import pool
        matchups = pool.role_dataset(s, "BOTTOM")["matchups"]
        expected = sorted(
            ((b, g, round(w / g * 100)) for (a, b), (g, w) in matchups.items()
             if a == "Jinx" and g >= builds.MIN_MATCHUP_GAMES),
            key=lambda r: -r[1])
        assert rows == expected


def test_champion_matchups_skips_malformed_lanes(session_factory):
    # A match with three named BOTTOM laners is not a 1:1 lane — the
    # role_dataset well-formed-SR guard must hold here too.
    match = make_match("EUN1_bad")
    parts = match["info"]["participants"]
    parts[3]["championName"] = "Jinx"
    parts[8]["championName"] = "Ashe"
    parts[4]["teamPosition"] = "BOTTOM"  # third bottom laner
    with session_factory() as s:
        store.insert_match_bundle(s, match, make_timeline("EUN1_bad"), region="europe")
    for i in range(2):
        store_match_with_champs(session_factory, f"EUN1_ok{i}")

    with session_factory() as s:
        assert builds.champion_matchups(s, "Jinx", "BOTTOM") == [("Ashe", 2, 100)]


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

"""Offline tests for the bulk meta-sync bundle (op.gg exit contract)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import metasync, store
from app.models import Base

from tests.test_metabuild import jinx_match


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def seed(session_factory, count=10, **kw):
    with session_factory() as s:
        for i in range(count):
            m, t = jinx_match(f"EUN1_{i}", **kw)
            store.insert_match_bundle(s, m, t, region="europe")


def test_bundle_contract(session_factory):
    seed(session_factory, count=10, win=True)
    with session_factory() as s:
        bundle = metasync.build_sync_bundle(s, min_games=8)
    assert bundle["patch"]
    jinx = next(e for e in bundle["entries"] if e["champion"] == "Jinx")
    assert jinx["champion_id"] == 222
    assert jinx["role"] == "BOTTOM"
    assert jinx["games"] == 10
    assert jinx["win_rate"] == 1.0
    assert jinx["tier"] == 1  # 100% WR but under the 20-game S+ bar
    assert 0 < jinx["pick_rate"] <= 0.5
    # lane counter contract: opponent Filler8 (BOTTOM, team 200), Jinx wins all
    assert jinx["counters"] == [{"champion_id": 1008, "opp_winrate": 1.0}]
    # synergy contract: 4 same-team allies, all with 10 shared wins
    ally_ids = {s["synergy_champion_id"] for s in jinx["synergies"]}
    assert ally_ids == {1000, 1001, 1002, 1004}
    assert all(s["win_rate"] == 1.0 for s in jinx["synergies"])
    # the build payload rides along in the exact opgg shape
    assert jinx["payload"]["core_item_ids"]
    assert jinx["payload"]["role"] == "BOTTOM"


def test_min_games_filters_entries(session_factory):
    seed(session_factory, count=5)
    with session_factory() as s:
        bundle = metasync.build_sync_bundle(s, min_games=8)
    assert all(e["champion"] != "Jinx" or e["games"] >= 8 for e in bundle["entries"])
    assert not any(e["champion"] == "Jinx" for e in bundle["entries"])


def test_tier_buckets():
    assert metasync._tier(0.55, 25) == 0
    assert metasync._tier(0.55, 10) == 1   # not enough games for S+
    assert metasync._tier(0.50, 30) == 2
    assert metasync._tier(0.45, 30) == 3

"""End-to-end advice pipeline over stored data (SQLite in-memory)."""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import store
from app.advice.pipeline import AdviceNotPossible, get_or_generate_advice
from app.models import Advice, Base

from tests.test_store_crawler import make_match
from tests.test_advice import CORE_ITEM, build_view, item_event, kill_event


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def store_bundle(session_factory, match_id="EUN1_100", events=None, cs_per_min=3):
    match = make_match(match_id)
    view = build_view(events=events or [], cs_per_min=cs_per_min)
    timeline = {"metadata": {"matchId": match_id},
                "info": {"frames": view.frames, "frameInterval": 60000}}
    with session_factory() as s:
        store.insert_match_bundle(s, match, timeline, region="europe")


def test_advice_generated_and_cached(session_factory):
    # puuid-1 = participant 1, TOP, low farm (cs@10=30) → cs_low advice
    store_bundle(session_factory)
    with session_factory() as s:
        first = get_or_generate_advice(s, "EUN1_100", "puuid-1", lang="hu")
        assert first["cached"] is False
        assert first["top_finding"]["type"] == "cs_benchmark"
        assert first["text"] == first["text_hu"]
        assert "CS" in first["text_hu"]

        second = get_or_generate_advice(s, "EUN1_100", "puuid-1", lang="en")
        assert second["cached"] is True
        assert second["text"] == second["text_en"]
        assert second["top_finding"] == first["top_finding"]
        assert s.scalar(select(func.count()).select_from(Advice)) == 1


def test_advice_prefers_worst_finding(session_factory):
    # moderate farm deficit (severity ~50) AND 5 outnumbered deaths (severity 80)
    # → death_context must win
    events = [kill_event(m, killer=6, assists=(7, 8)) for m in (6, 10, 14, 18, 22)]
    events += [item_event(13, CORE_ITEM), item_event(22, CORE_ITEM)]  # items on time
    store_bundle(session_factory, match_id="EUN1_101", events=events, cs_per_min=5)
    with session_factory() as s:
        result = get_or_generate_advice(s, "EUN1_101", "puuid-1")
        types = {f["type"] for f in result["all_findings"]}
        assert "cs_benchmark" in types and "death_context" in types
        assert result["top_finding"]["type"] == "death_context"


def test_unknown_match_raises(session_factory):
    with session_factory() as s:
        with pytest.raises(AdviceNotPossible):
            get_or_generate_advice(s, "EUN1_nope", "puuid-1")


def test_unknown_player_raises(session_factory):
    store_bundle(session_factory, match_id="EUN1_102")
    with session_factory() as s:
        with pytest.raises(AdviceNotPossible):
            get_or_generate_advice(s, "EUN1_102", "puuid-ghost")

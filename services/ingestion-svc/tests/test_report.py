"""Offline tests for the weekly trend report (SQLite, synthetic bundles)."""
import time

import pytest
from app import report, store
from app.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.test_advice import CORE_ITEM, build_view, item_event
from tests.test_store_crawler import make_match

PUUID = "puuid-1"
NOW_MS = int(time.time() * 1000)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def store_game(session_factory, match_id, *, win=True, age_days=1.0, champion="Champ0",
               cs_per_min=7):
    match = make_match(match_id)
    match["info"]["gameCreation"] = NOW_MS - int(age_days * 86400_000)
    p1 = match["info"]["participants"][0]
    p1["win"] = win
    p1["championName"] = champion
    events = [item_event(13, CORE_ITEM), item_event(22, CORE_ITEM)]
    view = build_view(events=events, cs_per_min=cs_per_min)
    timeline = {"info": {"frames": view.frames, "frameInterval": 60000}}
    with session_factory() as s:
        store.insert_match_bundle(s, match, timeline, region="europe")


def test_report_aggregates_window(session_factory):
    store_game(session_factory, "EUN1_1", win=True, age_days=1, champion="Ashe")
    store_game(session_factory, "EUN1_2", win=False, age_days=2, champion="Ashe")
    store_game(session_factory, "EUN1_3", win=True, age_days=3, champion="Jinx")
    store_game(session_factory, "EUN1_old", win=True, age_days=30)  # outside window

    with session_factory() as s:
        data = report.build_report(s, PUUID, days=7)
    assert data["games"] == 3
    assert data["wins"] == 2 and data["losses"] == 1
    assert data["winrate_pct"] == 67
    assert len(data["form"]) == 3
    assert data["top_champs"][0]["name"] == "Ashe"
    assert data["top_champs"][0]["games"] == 2


def test_report_empty_window_returns_none(session_factory):
    store_game(session_factory, "EUN1_old", age_days=30)
    with session_factory() as s:
        assert report.build_report(s, PUUID, days=7) is None


def test_report_focus_is_most_recurring_finding(session_factory):
    # low farm in every game → cs_benchmark should dominate the focus
    for i in range(3):
        store_game(session_factory, f"EUN1_{i}", age_days=i + 1, cs_per_min=3)
    with session_factory() as s:
        data = report.build_report(s, PUUID, days=7)
    assert data["focus_type"] == "cs_benchmark"
    assert data["cs10_delta_avg"] is not None
    assert data["cs10_delta_avg"] < 0


def test_render_hu_en_and_payload(session_factory):
    store_game(session_factory, "EUN1_1", age_days=1, cs_per_min=3)
    with session_factory() as s:
        data = report.build_report(s, PUUID, days=7)
    hu = report.render_text(data, "hu")
    en = report.render_text(data, "en")
    assert "meccs" in hu and "games" in en and hu != en
    payload = report.build_report_payload(data, "hu")
    assert payload["embeds"][0]["title"].endswith("Heti összefoglaló")
    assert "1 games" in payload["embeds"][0]["footer"]["text"]

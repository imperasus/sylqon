"""Offline store + crawler tests on in-memory SQLite (shared via StaticPool)."""
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import store
from app.crawler import AccountNotFound, IngestService
from app.models import Base, Match, MatchParticipant, Timeline


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def make_match(match_id: str, puuids=None) -> dict:
    puuids = puuids or [f"puuid-{i}" for i in range(1, 11)]
    return {
        "metadata": {"matchId": match_id, "participants": puuids},
        "info": {
            "queueId": 420,
            "gameCreation": 1750000000000,
            "gameDuration": 1900,
            "gameVersion": "14.23.634.7472",
            "participants": [
                {
                    "puuid": p,
                    "participantId": i + 1,
                    "teamId": 100 if i < 5 else 200,
                    "championId": 100 + i,
                    "championName": f"Champ{i}",
                    "teamPosition": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][i % 5],
                    "win": i < 5,
                    "kills": i,
                    "deaths": 2,
                    "assists": 3,
                    "goldEarned": 10000 + i,
                    "totalMinionsKilled": 150,
                    "neutralMinionsKilled": 20,
                    "visionScore": 25,
                    "wardsPlaced": 10,
                    "visionWardsBoughtInGame": 2,
                    "totalDamageDealtToChampions": 15000,
                }
                for i, p in enumerate(puuids)
            ],
        },
    }


def make_timeline(match_id: str) -> dict:
    return {"metadata": {"matchId": match_id}, "info": {"frames": [], "frameInterval": 60000}}


def make_riot(match_ids, matches=None, timelines=None, account=None):
    riot = MagicMock()
    riot.mass_region = "europe"
    riot.get_account_by_riot_id.return_value = (
        account if account is not None else {"puuid": "puuid-1"}
    )
    riot.get_match_ids.return_value = match_ids
    matches = matches or {m: make_match(m) for m in match_ids}
    timelines = timelines or {m: make_timeline(m) for m in match_ids}
    riot.get_match.side_effect = lambda mid: matches.get(mid)
    riot.get_timeline.side_effect = lambda mid: timelines.get(mid)
    return riot


def test_ingest_inserts_matches_participants_timelines(session_factory):
    ids = ["EUN1_1", "EUN1_2", "EUN1_3"]
    service = IngestService(make_riot(ids), session_factory)
    result = service.ingest("Name", "TAG")
    assert result.inserted == 3
    assert result.inserted_timelines == 3
    assert result.skipped_existing == 0
    assert result.failed == []
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Match)) == 3
        assert s.scalar(select(func.count()).select_from(MatchParticipant)) == 30
        assert s.scalar(select(func.count()).select_from(Timeline)) == 3


def test_reingest_is_idempotent_and_skips_api_calls(session_factory):
    ids = ["EUN1_1", "EUN1_2"]
    riot = make_riot(ids)
    service = IngestService(riot, session_factory)
    service.ingest("Name", "TAG")
    riot.get_match.reset_mock()
    riot.get_timeline.reset_mock()

    result = service.ingest("Name", "TAG")
    assert result.inserted == 0
    assert result.skipped_existing == 2
    riot.get_match.assert_not_called()  # known matches cost zero API calls
    riot.get_timeline.assert_not_called()
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Match)) == 2
        assert s.scalar(select(func.count()).select_from(MatchParticipant)) == 20


def test_failed_match_fetch_is_isolated(session_factory):
    ids = ["EUN1_1", "EUN1_2", "EUN1_3"]
    matches = {m: make_match(m) for m in ids}
    matches["EUN1_2"] = None  # this one 404s / times out
    service = IngestService(make_riot(ids, matches=matches), session_factory)
    result = service.ingest("Name", "TAG")
    assert result.inserted == 2
    assert result.failed == ["EUN1_2"]


def test_missing_timeline_keeps_match_retryable(session_factory):
    ids = ["EUN1_1"]
    timelines = {"EUN1_1": None}
    service = IngestService(make_riot(ids, timelines=timelines), session_factory)
    result = service.ingest("Name", "TAG")
    assert result.inserted == 0
    assert result.failed == ["EUN1_1"]
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Match)) == 0  # nothing partial


def test_unknown_account_raises(session_factory):
    service = IngestService(make_riot([], account={}), session_factory)
    with pytest.raises(AccountNotFound):
        service.ingest("Ghost", "EUNE")


def test_derive_patch():
    assert store.derive_patch("14.23.634.7472") == "14.23"
    assert store.derive_patch("15.1") == "15.1"
    assert store.derive_patch(None) is None
    assert store.derive_patch("") is None


def test_stored_columns_match_payload(session_factory):
    service = IngestService(make_riot(["EUN1_9"]), session_factory)
    service.ingest("Name", "TAG")
    with session_factory() as s:
        match = s.get(Match, "EUN1_9")
        assert match.platform == "EUN1"
        assert match.patch == "14.23"
        assert match.queue_id == 420
        p = s.get(MatchParticipant, ("EUN1_9", "puuid-3"))
        assert p.participant_id == 3
        assert p.control_wards_bought == 2
        assert p.stats["championName"] == "Champ2"

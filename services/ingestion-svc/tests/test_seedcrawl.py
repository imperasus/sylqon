"""Offline tests for the co-player seed crawl."""
from datetime import datetime, timedelta, timezone

import pytest
from app import config, seedcrawl, store
from app.crawler import IngestService
from app.models import Base, CrawlTarget, LinkedAccount, Match
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.test_store_crawler import make_match, make_riot, make_timeline


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def enable_crawl(monkeypatch):
    monkeypatch.setattr(config, "CRAWL_ENABLED", True)
    monkeypatch.setattr(config, "CRAWL_BATCH", 2)
    monkeypatch.setattr(config, "CRAWL_MATCH_COUNT", 3)


def seed_one_match(session_factory, match_id="EUN1_1"):
    with session_factory() as s:
        store.insert_match_bundle(s, make_match(match_id), make_timeline(match_id),
                                  region="europe")


def test_discovery_excludes_linked_and_tracked(session_factory, monkeypatch):
    seed_one_match(session_factory)
    monkeypatch.setattr(config, "WATCH_PUUIDS", ["puuid-1"])
    with session_factory() as s:
        s.add(LinkedAccount(discord_user_id=1, puuid="puuid-2", game_name="X", tag_line="Y"))
        s.commit()
        added = seedcrawl.discover_targets(s)
        assert added == 8  # 10 participants − tracked − linked
        assert s.get(CrawlTarget, "puuid-1") is None
        assert s.get(CrawlTarget, "puuid-2") is None
        assert seedcrawl.discover_targets(s) == 0  # idempotent


def test_crawl_cycle_ingests_and_marks_targets(session_factory):
    seed_one_match(session_factory)
    riot = make_riot(["EUN1_2", "EUN1_3"])  # co-players' histories
    ingest = IngestService(riot, session_factory)
    inserted = seedcrawl.crawl_cycle(ingest, session_factory)
    assert inserted == 2  # both new matches stored once (2nd player skips them)
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Match)) == 3
        crawled = [t for t in s.execute(select(CrawlTarget)).scalars()
                   if t.last_crawled_at is not None]
        assert len(crawled) == 2  # CRAWL_BATCH


def test_recrawl_only_after_cutoff(session_factory):
    seed_one_match(session_factory)
    now = datetime.now(timezone.utc)
    with session_factory() as s:
        seedcrawl.discover_targets(s)
        for i, t in enumerate(s.execute(select(CrawlTarget)).scalars()):
            t.last_crawled_at = now - timedelta(hours=1 if i < 7 else 100)
        s.commit()
        batch = seedcrawl.next_batch(s, batch=5)
        # only the 3 stale (100h) targets qualify; the 7 fresh (1h) are skipped
        assert len(batch) == 3


def test_crawl_disabled_is_noop(session_factory, monkeypatch):
    monkeypatch.setattr(config, "CRAWL_ENABLED", False)
    seed_one_match(session_factory)
    riot = make_riot(["EUN1_2"])
    assert seedcrawl.crawl_cycle(IngestService(riot, session_factory), session_factory) == 0
    riot.get_match_ids.assert_not_called()

"""Co-player seed crawl: grow the dataset from PUUIDs we already met.

Discovery: every stored match's participants are upserted into crawl_targets.
Crawling: each cycle takes the least-recently-crawled batch and ingests their
recent matches (which in turn discovers more players). Tracked/linked accounts
are excluded — the watcher already covers them at a faster cadence.

Quota math (production key, 450/10s budget): one crawled player ≈ 1 + 2×M
requests; the default batch of 3 × 10 matches ≈ 63 requests per cycle, far
under one burst window — and the ids→exists check keeps recrawls nearly free.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.crawler import IngestService
from app.models import CrawlTarget, LinkedAccount, MatchParticipant

log = logging.getLogger(__name__)


def discover_targets(session: Session) -> int:
    """Upsert every participant PUUID we have stored into crawl_targets."""
    known = {r[0] for r in session.execute(select(CrawlTarget.puuid))}
    linked = {r[0] for r in session.execute(select(LinkedAccount.puuid))}
    added = 0
    for (puuid,) in session.execute(select(MatchParticipant.puuid).distinct()):
        if puuid in known or puuid in linked or puuid in config.WATCH_PUUIDS:
            continue
        session.add(CrawlTarget(puuid=puuid))
        added += 1
    if added:
        session.commit()
    return added


def next_batch(session: Session, batch: int | None = None) -> list[CrawlTarget]:
    """Least-recently-crawled targets; never-crawled first, then stale ones."""
    batch = batch or config.CRAWL_BATCH
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.CRAWL_RECRAWL_HOURS)
    rows = list(
        session.execute(
            select(CrawlTarget)
            .where(
                (CrawlTarget.last_crawled_at.is_(None))
                | (CrawlTarget.last_crawled_at < cutoff)
            )
            .order_by(CrawlTarget.last_crawled_at.asc().nulls_first())
            .limit(batch)
        ).scalars()
    )
    return rows


def crawl_cycle(ingest: IngestService, session_factory: sessionmaker) -> int:
    """One discovery + crawl batch. Returns matches newly inserted."""
    if not config.CRAWL_ENABLED:
        return 0
    inserted = 0
    with session_factory() as session:
        new = discover_targets(session)
        if new:
            log.info("seed crawl discovered %d new player(s)", new)
        targets = next_batch(session)

    for target in targets:
        result = ingest.ingest_by_puuid(target.puuid, count=config.CRAWL_MATCH_COUNT)
        inserted += result.inserted
        with session_factory() as session:
            row = session.get(CrawlTarget, target.puuid)
            if row:
                row.last_crawled_at = datetime.now(timezone.utc)
                session.commit()
    if inserted:
        log.info("seed crawl ingested %d new match(es) from %d player(s)",
                 inserted, len(targets))
    return inserted

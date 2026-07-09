"""Ingest pipeline: Riot ID → PUUID → match ids → match + timeline → Postgres.

Idempotent and quota-frugal: known matches are skipped *before* any API call,
so a rerun of the same summoner costs 2 requests (account + ids), not 42.
A match is only persisted when both the match and its timeline were fetched —
a partial fetch stays retryable on the next run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import sessionmaker

from app import config, regions, store
from app.riot_client import RiotClient

log = logging.getLogger(__name__)


class AccountNotFound(Exception):
    pass


@dataclass
class IngestResult:
    puuid: str
    requested_count: int
    match_ids_found: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    inserted_timelines: int = 0
    failed: list[str] = field(default_factory=list)


class IngestService:
    def __init__(self, riot: RiotClient, session_factory: sessionmaker) -> None:
        self._riot = riot
        self._session_factory = session_factory

    def ingest(self, game_name: str, tag_line: str, count: int | None = None,
               platform: str | None = None) -> IngestResult:
        """Ingest by Riot ID. ``platform`` (euw1, na1, …) selects the regional
        cluster for Account-V1 + Match-V5; defaults to the client's mass region."""
        cluster = regions.cluster_for(platform) if platform else self._riot.mass_region
        account = self._riot.get_account_by_riot_id(game_name, tag_line, region=cluster)
        if not account or not account.get("puuid"):
            raise AccountNotFound(f"Riot ID not found: {game_name}#{tag_line}")
        return self.ingest_by_puuid(account["puuid"], count, cluster=cluster)

    def ingest_by_puuid(self, puuid: str, count: int | None = None,
                        cluster: str | None = None) -> IngestResult:
        count = count or config.RIOT_MATCH_COUNT
        cluster = cluster or self._riot.mass_region
        result = IngestResult(puuid=puuid, requested_count=count)

        match_ids = self._riot.get_match_ids(puuid, count=count, region=cluster)
        result.match_ids_found = len(match_ids)

        with self._session_factory() as session:
            for match_id in match_ids:
                if store.match_exists(session, match_id):
                    result.skipped_existing += 1
                    continue

                match = self._riot.get_match(match_id, region=cluster)
                timeline = self._riot.get_timeline(match_id, region=cluster)
                if not match or not timeline:
                    log.warning("skipping %s: match=%s timeline=%s",
                                match_id, bool(match), bool(timeline))
                    result.failed.append(match_id)
                    continue

                try:
                    if store.insert_match_bundle(
                        session, match, timeline, region=cluster
                    ):
                        result.inserted += 1
                        result.inserted_timelines += 1
                    else:
                        result.skipped_existing += 1  # raced/duplicate id in the list
                except Exception:
                    log.exception("failed to persist %s", match_id)
                    session.rollback()
                    result.failed.append(match_id)

        return result

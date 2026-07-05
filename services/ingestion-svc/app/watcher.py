"""Match watcher: poll tracked PUUIDs → ingest new matches → advise → deliver.

The "proactive post-game message" of the roadmap's Phase 1, webhook edition.
Dedupe lives in the ``deliveries`` table; on the very first cycle every
already-stored match is *baselined* (marked delivered without sending) so a
fresh watcher never floods the channel with the ingest backlog.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import aggregate, config, store
from app.advice.pipeline import AdviceNotPossible, get_or_generate_advice
from app.crawler import IngestService
from app.models import Delivery, LinkedAccount, MatchParticipant
from app.notifier import DiscordWebhookNotifier

log = logging.getLogger(__name__)


def _undelivered_match_ids(session: Session, puuid: str) -> list[str]:
    delivered = select(Delivery.match_id).where(Delivery.puuid == puuid)
    rows = session.execute(
        select(MatchParticipant.match_id)
        .where(MatchParticipant.puuid == puuid)
        .where(MatchParticipant.match_id.not_in(delivered))
    )
    return [r[0] for r in rows]


def _mark_delivered(session: Session, match_id: str, puuid: str, channel: str) -> None:
    session.add(Delivery(match_id=match_id, puuid=puuid, channel=channel))
    session.commit()


class MatchWatcher:
    def __init__(
        self,
        ingest: IngestService,
        session_factory: sessionmaker,
        notifier: DiscordWebhookNotifier,
        puuids: list[str] | None = None,
        lang: str | None = None,
    ) -> None:
        self._ingest = ingest
        self._session_factory = session_factory
        self._notifier = notifier
        self._puuids = puuids if puuids is not None else config.WATCH_PUUIDS
        self._lang = lang or config.WATCH_LANG
        self._baselined: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _tracked_puuids(self) -> list[str]:
        """Static config accounts + every /link-ed Discord user."""
        puuids = list(self._puuids)
        with self._session_factory() as session:
            for row in session.execute(select(LinkedAccount.puuid)):
                if row[0] not in puuids:
                    puuids.append(row[0])
        return puuids

    def run_once(self) -> int:
        """One poll cycle. Returns the number of advice messages delivered."""
        delivered = 0
        for puuid in self._tracked_puuids():
            try:
                delivered += self._poll_puuid(puuid)
            except Exception:
                log.exception("watcher cycle failed for %s", puuid)
        try:
            from app import seedcrawl

            if seedcrawl.crawl_cycle(self._ingest, self._session_factory):
                with self._session_factory() as session:
                    aggregate.refresh_benchmarks(session)
        except Exception:
            log.exception("seed crawl cycle failed")
        return delivered

    def _poll_puuid(self, puuid: str) -> int:
        result = self._ingest.ingest_by_puuid(puuid, count=config.WATCH_MATCH_COUNT)
        delivered = 0
        with self._session_factory() as session:
            if result.inserted:
                aggregate.refresh_benchmarks(session)  # own-data medians stay current
            pending = _undelivered_match_ids(session, puuid)

            # First sight of this puuid → baseline the backlog silently.
            if puuid not in self._baselined:
                self._baselined.add(puuid)
                has_history = bool(
                    session.execute(
                        select(Delivery.match_id).where(Delivery.puuid == puuid).limit(1)
                    ).first()
                )
                if not has_history and pending:
                    log.info("baselining %d stored matches for %s…", len(pending), puuid[:12])
                    for match_id in pending:
                        _mark_delivered(session, match_id, puuid, channel="baseline")
                    return 0

            for match_id in pending:
                try:
                    advice = get_or_generate_advice(session, match_id, puuid, lang=self._lang)
                except AdviceNotPossible as exc:
                    log.warning("no advice for %s: %s", match_id, exc)
                    continue
                participant = store.get_participant(session, match_id, puuid)
                if self._notifier.send(advice, participant, lang=self._lang):
                    _mark_delivered(session, match_id, puuid, channel="discord")
                    delivered += 1
                    log.info("delivered advice for %s (%s)", match_id, advice["champion"])
                # send failure → left undelivered, retried next cycle
        return delivered

    # -- background loop -----------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="match-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        log.info(
            "match watcher started: %d account(s), every %.0fs, lang=%s",
            len(self._puuids), config.WATCH_POLL_SECONDS, self._lang,
        )
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(config.WATCH_POLL_SECONDS)

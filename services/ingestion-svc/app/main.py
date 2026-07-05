"""FastAPI entrypoint for the ingestion + advice service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query

from app import config, db
from app.crawler import AccountNotFound, IngestService
from app.notifier import DiscordWebhookNotifier
from app.ratelimit import build_rate_limiter
from app.riot_client import RiotClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

_ingest_service: IngestService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ingest_service
    if not config.RIOT_API_KEY:
        raise RuntimeError("RIOT_API_KEY is not set — refusing to start")
    engine = db.init_db()
    riot = RiotClient(rate_limiter=build_rate_limiter())
    _ingest_service = IngestService(riot, db.get_session_factory(engine))
    log.info("ingestion service ready (mass_region=%s, ratelimit=%s)",
             config.RIOT_MASS_REGION, config.RATELIMIT_MODE)

    watcher = None
    notifier = DiscordWebhookNotifier()
    if notifier.enabled and config.WATCH_PUUIDS:
        from app.watcher import MatchWatcher

        watcher = MatchWatcher(_ingest_service, db.get_session_factory(engine), notifier)
        watcher.start()
    yield
    if watcher:
        watcher.stop()


app = FastAPI(title="Sylqon Ingestion Service", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/api/ingest")
def ingest(
    game_name: str = Query(..., min_length=1),
    tag_line: str = Query(..., min_length=1),
    count: int = Query(default=None, ge=1, le=100),
) -> dict:
    """Fetch the summoner's last N matches + timelines into Postgres. Sync on
    purpose: a 20-match run is ~42 requests and finishes in seconds under the
    production-key limiter."""
    assert _ingest_service is not None
    try:
        result = _ingest_service.ingest(game_name, tag_line, count)
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return asdict(result)


@app.get("/api/advice/{match_id}/{puuid}")
def advice(match_id: str, puuid: str, lang: str = Query(default="hu")) -> dict:
    """Run the post-game heuristics on a stored match and return the top-1
    lesson with HU+EN template text. Cached per (match, player) — the pipeline
    is deterministic."""
    from app.advice.pipeline import AdviceNotPossible, get_or_generate_advice

    with db.open_session() as session:
        try:
            return get_or_generate_advice(session, match_id, puuid, lang=lang)
        except AdviceNotPossible as exc:
            raise HTTPException(status_code=404, detail=str(exc))

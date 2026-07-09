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

from app.web import router as web_router  # noqa: E402

app.include_router(web_router)  # public S3 pages: /, /pool-report, /champions, /champion/{name}


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


@app.get("/api/pool/{game_name}/{tag_line}")
def pool_report(game_name: str, tag_line: str, refresh: bool = Query(default=True)) -> dict:
    """Champion-pool coverage report (Phase 2 / S3 core): ingest the player's
    recent matches (optional), then score their per-role pool on performance,
    blind-pick safety and counter coverage from our own aggregation."""
    from app import pool as pool_mod

    assert _ingest_service is not None
    try:
        result = _ingest_service.ingest(game_name, tag_line) if refresh else None
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    puuid = result.puuid if result else None
    with db.open_session() as session:
        if puuid is None:
            account = _ingest_service._riot.get_account_by_riot_id(game_name, tag_line)
            if not account or not account.get("puuid"):
                raise HTTPException(status_code=404, detail="Riot ID not found")
            puuid = account["puuid"]
        report = pool_mod.analyze_pool(session, puuid)
    if report is None:
        raise HTTPException(status_code=404, detail="no stored matches for this player yet")
    report["riot_id"] = f"{game_name}#{tag_line}"
    return report


@app.get("/api/summoner/{game_name}/{tag_line}")
def summoner_profile(game_name: str, tag_line: str) -> dict:
    """Summoner profile DTO: Account-V1 + Summoner-V4 level + League-V4 rank +
    Mastery-V4 top champions in one response. 404 if the Riot ID resolves to no
    account. Descriptive display of the player's own official Riot data — no
    skill/MMR estimate (S3 framing)."""
    from app import profile as profile_mod

    assert _ingest_service is not None
    result = profile_mod.build_profile(_ingest_service._riot, game_name, tag_line)
    if result is None:
        raise HTTPException(status_code=404, detail="Riot ID not found")
    return result


@app.get("/api/meta-sync/full")
def meta_sync_full(min_games: int = Query(default=8, ge=3)) -> dict:
    """Everything the local app's full sync needs in one response (meta stats,
    build payloads, counters, synergies) — the bulk op.gg replacement. Heavy on
    a cold cache; prewarm with `python -m app.cli metasync`."""
    from app import metasync

    with db.open_session() as session:
        return metasync.build_sync_bundle(session, min_games=min_games)


@app.get("/api/meta-build/{champion}")
def meta_build(champion: str, role: str = Query(..., min_length=2)) -> dict:
    """Own-data build payload in the op.gg payload shape the local client's
    opgg_to_build converter consumes — the op.gg replacement source. 404 below
    the sample floor so the client can fall back."""
    from app import metabuild

    with db.open_session() as session:
        payload = metabuild.get_meta_build(session, champion, role)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"not enough stored games for {champion} ({role}) yet",
        )
    return payload


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

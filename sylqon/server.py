"""FastAPI bridge between the pipeline runtime and the Hextech dashboard.

The dashboard polls GET /api/state (~1.5s); actions are plain POSTs. If the
UI has been built (ui/dist exists) it is served from /, so production is a
single `python -m sylqon.server` on http://127.0.0.1:8077.
"""
from __future__ import annotations

import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sylqon import config
from sylqon.ai.match_review import MatchReviewAnalyzer
from sylqon.analysis.scoring import ChampionScorer
from sylqon.cache.opgg import opgg_to_build
from sylqon.db import matches as match_store
from sylqon.db import queries
from sylqon.db.schema import (
    Champion, ChampionCounter, ChampionSynergy, MatchHistory,
)
from sylqon.main import setup_logging
from sylqon.mcp import ingest
from sylqon.runtime import PipelineRunner
from sylqon.db.session import get_session, init_db

HOST, PORT = "127.0.0.1", 8077
UI_DIST = config.PROJECT_ROOT / "ui" / "dist"

runner = PipelineRunner()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # ensure the v2 SQLite tables exist (idempotent)
    thread = threading.Thread(target=runner.run_forever, name="ag-pipeline", daemon=True)
    thread.start()
    yield
    runner.stop()


app = FastAPI(title="Sylqon", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InjectRequest(BaseModel):
    variant: str = "optimized"   # "optimized" | "standard"


class InjectVariantRequest(BaseModel):
    index: int = 0               # index into state.build.variants (0 = primary)


class PoolRequest(BaseModel):
    pool: dict[str, list[str]]   # role -> [champion names]


class OPGGBuildRequest(BaseModel):
    champion: str
    role: str                        # top/jungle/middle/bottom/utility
    starter_item_ids: list[int] = []
    boot_ids: list[int] = []
    core_item_ids: list[int] = []
    fourth_item_ids: list[int] = []
    fifth_item_ids: list[int] = []
    sixth_item_ids: list[int] = []
    primary_page_id: int = 0
    primary_rune_ids: list[int] = []
    secondary_page_id: int = 0
    secondary_rune_ids: list[int] = []
    stat_mod_ids: list[int] = []
    summoner_spell_ids: list[int] = []
    skill_order: list[str] = []      # max priority, e.g. ["Q", "W", "E"] (R omitted)


# --- v2 op.gg ingest payloads (Claude-driven; see sylqon/mcp/sync.py) ---
class LaneMetaEntryReq(BaseModel):
    champion: str
    tier: int | None = None
    win_rate: float = 0.0   # op.gg fraction (0.55)
    pick_rate: float = 0.0


class LaneMetaReq(BaseModel):
    position: str           # adc/mid/jungle/top/support (normalized server-side)
    entries: list[LaneMetaEntryReq] = []


class CounterEntryReq(BaseModel):
    champion_name: str
    win_rate: float = 0.0


class CountersReq(BaseModel):
    champion: str
    position: str
    strong_counters: list[CounterEntryReq] = []
    weak_counters: list[CounterEntryReq] = []


class SynergyEntryReq(BaseModel):
    synergy_champion_name: str
    win_rate: float = 0.0


class SynergiesReq(BaseModel):
    champion: str
    position: str
    synergies: list[SynergyEntryReq] = []


class RecommendReq(BaseModel):
    role: str                       # top/jungle/middle/bottom/utility (or op.gg vocab)
    allies: list[str] = []          # champion display names and/or numeric Riot keys
    enemies: list[str] = []
    limit: int = 5


class ProBuildItemReq(BaseModel):
    id: int
    name: str = ""


class ProBuildReq(BaseModel):
    """A pro/esports player's build (Claude posts this after resolving the pro via
    lol_get_pro_player_riot_id + lol_get_summoner_game_detail)."""
    champion: str
    role: str                       # op.gg or normalized vocab
    pro_name: str
    team: str = ""
    region: str = ""
    patch: str = ""
    result: str = ""                # "Win" | "Loss" (optional)
    items: list[ProBuildItemReq] = []
    skill_order: list[str] = []     # ["Q","W","E"]
    spell1: str = ""
    spell2: str = ""
    keystone: str = ""


@app.get("/api/state")
def get_state() -> dict:
    return runner.state.snapshot()


@app.get("/api/live/state")
def live_state() -> dict:
    """Normalized snapshot of the live game from Riot's read-only Live Client
    Data API (or ``{active: false}`` when no game is running). Debug/testing aid
    for the in-game overlay coach."""
    return runner.live_snapshot()


@app.get("/api/overlay/state")
def overlay_state() -> dict:
    """Everything the overlay needs: the ≤2 active missions (with role-aware text,
    progress and the live stats that matter) plus account-level progression."""
    from sylqon.livegame.progression import ProgressionService

    snap = runner.state.snapshot()
    overlay = snap.get("overlay") or {}
    champion = (overlay.get("game") or {}).get("champion", "")
    session = get_session()
    try:
        svc = ProgressionService()
        profile = svc.ensure_profile(session, (snap.get("lcu") or {}).get("summoner", ""))
        prof = svc.serialize_profile(profile)
        champ_prog = None
        cid = runner._resolve_champion_id(session, champion)
        if cid is not None:
            champ_prog = svc.serialize_champion_progress(
                svc.champion_progress(session, cid), champion)
        session.commit()
    finally:
        session.close()
    return {
        "active": overlay.get("active", False),
        "role": overlay.get("role", ""),
        "active_missions": overlay.get("missions", []),
        "game": overlay.get("game", {}),
        "profile": prof,
        "champion_progress": champ_prog,
    }


@app.post("/api/overlay/debug/reset")
def overlay_reset() -> dict:
    """Development helper: wipe progression + clear in-flight missions."""
    from sylqon.livegame.progression import ProgressionService

    session = get_session()
    try:
        ProgressionService().reset(session)
        session.commit()
    finally:
        session.close()
    runner.reset_overlay()
    return {"ok": True, "detail": "overlay progression reset"}


class LiveDemoReq(BaseModel):
    role: str = ""   # top/jungle/middle/bottom/utility (default: bottom / champ-select role)


@app.post("/api/live/demo")
def live_demo_start(req: LiveDemoReq) -> dict:
    """Start a simulated game so the overlay can be tested without launching
    League. READ-ONLY: this never touches the real client."""
    return runner.start_live_demo(req.role)


@app.delete("/api/live/demo")
def live_demo_stop() -> dict:
    return runner.stop_live_demo()


@app.post("/api/live/demo/last-match")
def live_demo_last_match() -> dict:
    """Populate the live state with end-of-game stats from the account owner's
    last ranked match. Useful for testing PlayersView without a running game.
    Requires RIOT_API_KEY and RIOT_SELF_PUUID to be configured."""
    from sylqon.riot import api as riot_api
    from sylqon.livegame.demo import match_to_live_state

    puuid = config.RIOT_SELF_PUUID
    if not puuid or not config.RIOT_API_KEY:
        return {"ok": False, "detail": "RIOT_API_KEY or RIOT_SELF_PUUID not set"}

    match_ids = riot_api.get_match_ids(puuid, 1)
    if not match_ids:
        return {"ok": False, "detail": "no recent ranked matches found"}

    match = riot_api.get_match(match_ids[0])
    if not match:
        return {"ok": False, "detail": f"failed to fetch {match_ids[0]}"}

    snap = match_to_live_state(match, puuid)
    runner.state.set("live", snap.to_dict())
    return {"ok": True, "match_id": match_ids[0], "players": len(snap.roster)}


@app.get("/overlay")
def overlay_page():
    """Serve the SPA for the minimal overlay route (OBS browser source). The
    React app reads the pathname and renders only the overlay. Registered before
    the StaticFiles mount so this exact path resolves in production."""
    index = UI_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"detail": "UI not built; run: npm run build --prefix ui"}


@app.post("/api/inject")
def force_inject(req: InjectRequest) -> dict:
    return runner.force_inject(req.variant)


@app.post("/api/inject/variant")
def inject_variant(req: InjectVariantRequest) -> dict:
    """Import a specific build variant (overwrites the previous import)."""
    return runner.inject_variant(req.index)


@app.post("/api/sync")
def manual_sync() -> dict:
    return runner.manual_sync()


@app.post("/api/sync/full")
def full_sync() -> dict:
    """Trigger a full op.gg → SQLite sync (all champions/roles) in the background.
    Progress is published to ``state.sync``."""
    return runner.start_full_sync()


@app.post("/api/pro-build")
def pro_build(req: ProBuildReq) -> dict:
    """Store one pro/esports player's build for a champion+role (Claude-driven via
    the op.gg MCP tools). Display-only — never injected."""
    build = {
        "items": [i.model_dump() for i in req.items],
        "skill_order": [s.upper() for s in req.skill_order if s.upper() in {"Q", "W", "E"}][:3],
        "spell1": req.spell1, "spell2": req.spell2, "keystone": req.keystone,
    }
    session = get_session()
    try:
        result = ingest.ingest_pro_build(
            session, req.champion, req.role, req.pro_name, build,
            team=req.team, region=req.region, patch=req.patch, result=req.result)
        session.commit()
    finally:
        session.close()
    return result


@app.get("/api/pro-builds")
def pro_builds(champion: str = "", role: str = "") -> dict:
    """Pro builds for a champion (optionally a single role), newest first."""
    patch = runner.catalog.patch
    session = get_session()
    try:
        builds = ingest.pro_builds_for(session, champion, role) if champion else []
    finally:
        session.close()
    return {"champion": champion, "role": role, "patch": patch, "pro_builds": builds}


ROLES = ("top", "jungle", "middle", "bottom", "utility")


@app.get("/api/pool")
def get_pool() -> dict:
    """The user-curated champion pool plus, per role, the champions we can
    actually build a loadout for (so the editor can hint coverage)."""
    return {
        "pool": runner.store.get_pool(),
        "buildable": {r: runner.store.buildable_for_role(r) for r in ROLES},
    }


@app.put("/api/pool")
def put_pool(req: PoolRequest) -> dict:
    saved = runner.store.set_pool(req.pool)
    runner.on_pool_changed()
    return {"pool": saved}


@app.get("/api/champion-stats")
def champion_stats() -> dict:
    """Per-champion win-rate + games from the local match history (SR queues),
    keyed by champion name. Empty until the client is connected."""
    return {"stats": runner.champion_stats_named()}


@app.get("/api/scout")
def scout(role: str = "bottom") -> dict:
    """The 'Ollama Meta Scout' recommendation for a role."""
    if role not in ROLES:
        role = "bottom"
    return runner.scout(role)


@app.get("/api/scout/lobby")
def scout_lobby() -> dict:
    """Pre-game lobby scouting: per-teammate playstyle fingerprints (role,
    champion pool, recent form, playstyle tags). ``ready`` is false until the
    first roster is profiled; anonymized players appear as hidden cards."""
    return runner.state.snapshot().get("scout") or {"players": [], "ready": False}


@app.get("/api/post-game")
def post_game() -> dict:
    """The auto-generated post-game review for the most recently finished game
    (match summary + AI analysis), or ``{active: false}`` when none is pending.
    Driven event-side by the end-of-game stats block; see runtime ``_on_eog``."""
    return runner.state.snapshot().get("post_game") or {"active": False}


@app.get("/api/champions")
def list_champions() -> dict:
    """All champions (name/slug/tags) for the pool editor's picker."""
    return {"champions": runner.catalog.all_champions()}


@app.get("/api/meta")
def meta_report() -> dict:
    """Current-patch strongest champions per role (cached from op.gg), enriched
    with champion slugs for icon rendering."""
    try:
        raw = json.loads(config.META_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"positions": {}, "patch": runner.catalog.short_patch, "source": ""}
    positions = {}
    for role, entries in raw.get("positions", {}).items():
        positions[role] = [
            {**e, "slug": runner.catalog.champion_slug(e.get("champion", ""))}
            for e in entries
        ]
    return {
        "positions": positions,
        "patch": runner.catalog.short_patch,
        "source": raw.get("source", ""),
    }


@app.post("/api/demo")
def start_demo() -> dict:
    return runner.start_demo()


@app.delete("/api/demo")
def stop_demo() -> dict:
    return runner.stop_demo()


@app.post("/api/opgg-build")
def opgg_build(req: OPGGBuildRequest) -> dict:
    """Accept a pre-parsed OP.GG champion analysis and store it in the cache.
    Called by Claude in-conversation via the OP.GG MCP tool, bypassing the
    search+text-parse pipeline."""
    build = opgg_to_build(req.model_dump(), runner.catalog)
    if not build:
        return {"detail": f"Could not convert OP.GG data for {req.champion} {req.role}"}
    runner.store.put_build(
        req.champion, req.role, build, "opgg", runner.catalog.patch
    )
    # v2: mirror into SQLite for the champion browser / build variants.
    session = get_session()
    try:
        ingest.mirror_build(session, req.champion, req.role, build, "opgg",
                            runner.catalog.patch)
        session.commit()
    finally:
        session.close()
    return {"detail": f"Cached {req.champion} {req.role} from OP.GG"}


@app.post("/api/ingest/lane-meta")
def ingest_lane_meta(req: LaneMetaReq) -> dict:
    """Populate champion roles + per-role meta tier/win/pick from an op.gg
    lane-meta list (lol_list_lane_meta_champions)."""
    session = get_session()
    try:
        result = ingest.ingest_lane_meta(
            session, req.position, [e.model_dump() for e in req.entries]
        )
        session.commit()
    finally:
        session.close()
    return result


@app.post("/api/ingest/counters")
def ingest_counters(req: CountersReq) -> dict:
    """Upsert counter advantages for a champion/role (from lol_get_champion_analysis)."""
    session = get_session()
    try:
        result = ingest.ingest_counters(
            session, req.champion, req.position,
            [e.model_dump() for e in req.strong_counters],
            [e.model_dump() for e in req.weak_counters],
        )
        session.commit()
    finally:
        session.close()
    return result


@app.post("/api/ingest/synergies")
def ingest_synergies(req: SynergiesReq) -> dict:
    """Upsert ally synergies for a champion/role (from lol_get_champion_analysis)."""
    session = get_session()
    try:
        result = ingest.ingest_synergies(
            session, req.champion, req.position,
            [e.model_dump() for e in req.synergies],
        )
        session.commit()
    finally:
        session.close()
    return result


@app.post("/api/recommend")
def recommend(req: RecommendReq) -> dict:
    """Universal top-N champion recommendation for a role and draft state.

    Scores ALL champions that can play ``role`` (not just the user's pool) 0-100
    on a counter/synergy/meta/win-rate blend. Enriches each with a slug+patch so
    the UI can render the icon."""
    role = ingest.norm_role(req.role)
    session = get_session()
    try:
        ally_ids = queries.ids_for_names(session, req.allies)
        enemy_ids = queries.ids_for_names(session, req.enemies)
        recs = ChampionScorer().get_top_recommendations(
            session, role, ally_ids, enemy_ids, req.limit
        )
    finally:
        session.close()
    patch = runner.catalog.patch
    for r in recs:
        r["champion"]["icon"] = _champ_icon(patch, r["champion"].get("slug"))
    return {"role": role, "patch": patch, "recommendations": recs}


def _champ_icon(patch: str, slug: str | None) -> str:
    return (f"https://ddragon.leagueoflegends.com/cdn/{patch}/img/champion/{slug}.png"
            if slug else "")


# --- v2 champion browser ----------------------------------------------------
@app.get("/api/champions/role/{role}")
def champions_by_role(role: str) -> dict:
    """Every champion that can play a role, with its per-role meta stats — feeds
    the dashboard champion browser."""
    role = ingest.norm_role(role)
    patch = runner.catalog.patch
    session = get_session()
    try:
        champs = queries.champions_for_role(session, role)
        out = [{
            "id": c.id, "name": c.name, "slug": c.slug, "riot_key": c.riot_key,
            "stats": (c.op_gg_stats or {}).get(role) or {},
            "icon": _champ_icon(patch, c.slug),
        } for c in champs]
    finally:
        session.close()
    out.sort(key=lambda c: (c["stats"].get("tier") if c["stats"].get("tier") is not None else 9,
                            -(c["stats"].get("win_rate") or 0)))
    return {"role": role, "patch": patch, "champions": out}


@app.get("/api/champions/{champion_id}/details")
def champion_details(champion_id: int, role: str = "") -> dict:
    """Counters, synergies and the cached build for a champion (optionally scoped
    to a role) — the champion-detail popup."""
    norm = ingest.norm_role(role) if role else ""
    patch = runner.catalog.patch
    session = get_session()
    try:
        champ = session.get(Champion, champion_id)
        if champ is None:
            return {"error": "champion not found"}

        def name_of(cid: int) -> tuple[str, str]:
            c = session.get(Champion, cid)
            return (c.name, c.slug or "") if c else ("Unknown", "")

        cq = session.query(ChampionCounter).filter(ChampionCounter.champion_id == champion_id)
        sq = session.query(ChampionSynergy).filter(ChampionSynergy.champion_id == champion_id)
        if norm:
            cq = cq.filter(ChampionCounter.role == norm)
            sq = sq.filter(ChampionSynergy.role == norm)

        counters = []
        for r in cq.all():
            n, slug = name_of(r.counter_id)
            counters.append({"name": n, "slug": slug, "icon": _champ_icon(patch, slug),
                             "advantage": r.advantage_score, "role": r.role})
        counters.sort(key=lambda x: x["advantage"] or 0)  # hardest counters first

        synergies = []
        for r in sq.all():
            n, slug = name_of(r.synergy_id)
            synergies.append({"name": n, "slug": slug, "icon": _champ_icon(patch, slug),
                              "score": r.synergy_score, "role": r.role})
        synergies.sort(key=lambda x: -(x["score"] or 0))

        build = queries.build_for(session, champion_id, norm) if norm else None
        result = {
            "champion": {"id": champ.id, "name": champ.name, "slug": champ.slug,
                         "icon": _champ_icon(patch, champ.slug), "roles": champ.roles or [],
                         "tags": champ.tags or [], "stats": champ.op_gg_stats or {}},
            "counters": counters,
            "synergies": synergies,
            "build": build.build_json if build else None,
        }
    finally:
        session.close()
    return result


# --- v2 match history + post-game analysis ----------------------------------
@app.get("/api/matches/recent")
def matches_recent(limit: int = 10) -> dict:
    """The last N games. Syncs fresh games from the LCU when connected, then
    returns the stored rows (with an ``has_analysis`` flag)."""
    session = get_session()
    try:
        if runner.client is not None and runner.client.is_alive():
            try:
                match_store.sync_recent_matches(session, runner.client, limit)
                session.commit()
            except Exception:
                logging.getLogger(__name__).warning("match sync failed", exc_info=True)
                session.rollback()
        rows = queries.recent_matches(session, limit)
        out = [match_store.serialize_match(session, m) for m in rows]
    finally:
        session.close()
    return {"matches": out, "patch": runner.catalog.patch}


@app.get("/api/matches/{match_id}/analysis")
def match_analysis(match_id: int) -> dict:
    """Return the stored AI analysis for a game, generating + persisting it on the
    first request."""
    session = get_session()
    try:
        m = session.get(MatchHistory, match_id)
        if m is None:
            return {"error": "match not found"}
        if m.analysis is not None:
            return {**match_store.serialize_analysis(m.analysis), "cached": True}

        md = match_store.match_to_analysis_input(session, m)
        result = MatchReviewAnalyzer(runner.engine).analyze_match(md)
        if result is None:
            return {"available": False,
                    "detail": "Ollama is offline; analysis could not be generated."}
        from sylqon.db.schema import MatchAnalysis
        session.add(MatchAnalysis(
            match_id=m.id, summary=result["summary"], strengths=result["strengths"],
            weaknesses=result["weaknesses"], tips=result["tips"],
        ))
        session.commit()
        return {**result, "cached": False}
    finally:
        session.close()


if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")


def run() -> None:
    setup_logging()
    logging.getLogger(__name__).info("Dashboard bridge on http://%s:%d", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    run()

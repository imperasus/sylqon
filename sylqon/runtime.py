"""Observable pipeline runtime.

Wraps the detection -> cache -> Ollama -> injection loop from the original
CLI entrypoint in a runner that publishes every state transition into a
thread-safe AppState snapshot, which the FastAPI bridge serves to the
dashboard. main.py (headless CLI) and server.py (dashboard) both run this.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
import time

from sylqon import config
from sylqon import loadout as loadout_mod
from sylqon.ai import build_variants, open_build_prompt
from sylqon.ai.engine import OllamaEngine
from sylqon.ai.pick_prompt import (
    apply_ai_pick,
    apply_universe_ai_pick,
    build_candidates,
    compile_pick_prompt,
    compile_universe_pick_prompt,
    heuristic_rank,
)
from sylqon.ai.prompts import compile_prompt
from sylqon.analysis import (
    ban_model, build_archetype, core_select, draft_intel, lane_matchup,
    player_callouts, power_curve, role_infer, rune_select,
)
from sylqon.analysis.scoring import ChampionScorer
from sylqon.cache.store import MetaCache
from sylqon.data import rune_pool, static
from sylqon.data.catalog import Catalog
from sylqon.lcu import scout as scout_mod
from sylqon.lcu.client import LCUClient
from sylqon.lcu.events import (
    CHAMP_SELECT_TOPIC,
    EOG_TOPIC,
    GAMEFLOW_TOPIC,
    LOBBY_TOPIC,
    LcuEventBus,
)
from sylqon.lcu.history import champion_stats
from sylqon.lcu.injector import Injector
from sylqon.lcu.lobby import (
    EnemyProfile,
    MatchContext,
    display_signature,
    parse_timer,
    read_match_context,
)
from sylqon.livegame.client import LiveClient
from sylqon.livegame.engine import MissionEngine
from sylqon.livegame.state import LiveGameState, parse_live_state
from sylqon.state import (
    AppState,
    StateLogHandler,
    serialize_enemy,
    serialize_loadout,
)

log = logging.getLogger(__name__)

DEMO_ENEMIES = [
    ("Malzahar", "middle"), ("Leona", "utility"), ("Zed", "jungle"),
    ("Soraka", "bottom"), ("Malphite", "top"),
]


def _tier_num(tier) -> int:
    """op.gg tier as a sortable number (lower = stronger); ``None`` sinks last."""
    return tier if tier is not None else 9


class PipelineRunner:
    def __init__(self, state: AppState | None = None) -> None:
        self.state = state or AppState()
        self.catalog = Catalog()
        self.store = MetaCache()
        self.engine = OllamaEngine()
        self.client: LCUClient | None = None
        self._event_bus: LcuEventBus | None = None
        # Always-on (while connected) bus carrying just the gameflow phase, so a
        # phase transition is acted on the instant it pushes — independent of the
        # per-phase ``_event_bus`` which is started/stopped by phase.
        self._gameflow_bus: LcuEventBus | None = None
        self._phase_lock = threading.Lock()
        self._summoner_id: int = 0
        self._compile_lock = threading.Lock()
        self._inject_lock = threading.Lock()
        self._variants_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._stop = threading.Event()
        self._catalog_lcu_supplemented = False
        # Build-cache freshness: a guard so a champion isn't refreshed twice
        # concurrently, a throttle for the periodic background warm-up, and a
        # throttle for the patch-change auto full-sync check.
        self._refresh_lock = threading.Lock()
        self._refreshing: set[tuple[str, str]] = set()
        self._warm_lock = threading.Lock()
        self._last_build_warm = 0.0
        self._last_auto_sync_check = 0.0
        # RAG item embedding index: rebuilt once per patch in the background when
        # SYLQON_RAG_ITEMS is enabled (guards the heavy embedding pass).
        self._rag_index_lock = threading.Lock()
        self._rag_index_patch = ""
        # In-game overlay coach: a dedicated read-only poller against the Live
        # Client Data API, spun up only while a game is InProgress.
        self._live_client = LiveClient()
        self._live_thread: threading.Thread | None = None
        self._live_stop = threading.Event()
        self._live_demo_thread: threading.Thread | None = None
        self._live_demo_stop = threading.Event()
        self._live_demo_role = "bottom"
        self._mission_engine = MissionEngine(
            on_resolve=self._on_mission_resolved,
            mission_source=self._champion_mission_source)
        self._was_in_game = False                # edge-trigger for end-of-game gen
        self._mission_gen_lock = threading.Lock()
        self.last_ctx: MatchContext | None = None
        self.last_candidate: dict | None = None
        self.last_meta_candidate: dict | None = None  # pre-core-selection page
        self.last_loadout: loadout_mod.Loadout | None = None
        self.last_standard: loadout_mod.Loadout | None = None
        self.last_variants: list[loadout_mod.Loadout] = []  # [0] = primary (auto-injected)
        self.last_matchup: dict | None = None               # post-lock scorecard
        self.last_lane_plan: dict | None = None              # AI early/mid/late plan
        self._last_injected_fp: str | None = None
        self._last_reco_fp: str | None = None
        self._last_display_sig: str | None = None
        self._last_trigger_sig: str | None = None
        self._champ_stats: dict[str, dict] = {}     # champion name -> {games, wins, win_rate}
        self._scout_cache: dict[str, dict] = {}     # role -> scout result (meta scout)
        # Pre-game lobby scouting: per-puuid playstyle fingerprints + a dedup
        # signature so a static lobby/draft is only scouted once.
        self._player_scout_cache: dict[str, dict] = {}   # puuid -> enriched fingerprint
        self._last_scout_sig: str | None = None
        # Local player's own rank, read from the LCU (works in custom/bot games
        # where the Spectator-based scout never runs). Cached per scout session.
        self._self_ranked: dict | None = None
        # Local player's PUUID — set on LCU connect; used for Spectator scouting.
        self._my_puuid: str = ""
        # Riot ID (gameName, tagLine) from the LCU — lets us recover the encrypted
        # PUUID via ACCOUNT-V1 when the LCU only gives a short internal id.
        self._my_riot_id: tuple[str, str] = ("", "")
        self._resolved_puuid: str = ""   # cached ACCOUNT-V1 result
        self._scout_lock = threading.Lock()
        # Auto post-game review: event-driven off the end-of-game stats block.
        self._last_reviewed_game: str | None = None
        self._review_lock = threading.Lock()
        self._last_role_top: list[dict] = []        # universal role top-N for live draft
        logging.getLogger("sylqon").addHandler(StateLogHandler(self.state))
        self._bootstrap_if_empty()
        self._prewarm_cache_from_db()

    def _prewarm_cache_from_db(self) -> None:
        """Network-free: mirror the already-synced DB build universe into the live
        injection cache so every champion is instantly buildable and the "X BUILDS"
        badge reflects the full set — without waiting for the next patch's auto
        full-sync. Only current-patch builds are added (so none are mislabelled as
        fresh), and existing cache entries (e.g. fresher live fetches) are kept.
        Best-effort: never breaks startup."""
        patch = self.catalog.patch
        if not patch:
            return  # catalog not loaded yet; the auto full-sync will pre-warm later
        try:
            from sylqon.db.schema import Champion, ChampionBuild
            from sylqon.db.session import get_session
            session = get_session()
            try:
                rows = (session.query(ChampionBuild, Champion.name)
                        .join(Champion, ChampionBuild.champion_id == Champion.id)
                        .filter(ChampionBuild.patch == patch)
                        .all())
            finally:
                session.close()
        except Exception:
            log.debug("DB cache pre-warm skipped", exc_info=True)
            return
        items = [(name, b.role, b.build_json, None)
                 for b, name in rows if b.build_json]
        if not items:
            return
        added = self.store.bulk_put_builds(items, patch, skip_existing=True)
        if added:
            log.info("Pre-warmed %d build(s) into the live cache from the DB universe", added)

    def _bootstrap_if_empty(self) -> None:
        """On fresh installs (no cached builds), fetch the catalog from Data
        Dragon and seed the MetaCache from the built-in BUILDS table."""
        if self.store.stats()["builds"] > 0:
            return
        log.info("Cache is empty — bootstrapping catalog and seed builds")
        self.catalog.refresh_if_stale()
        if not self.catalog.patch:
            log.warning("Catalog unavailable; bootstrap skipped (no network?)")
            return
        from sylqon.cache.seed import seed_cache
        seeded = seed_cache(self.store, self.catalog)
        log.info("Bootstrap complete: %d build(s) seeded", seeded)

    # ------------------------------------------------------------------ loop
    def run_forever(self) -> None:
        log.info("Antigravity pipeline running; waiting for the League client")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("Pipeline tick failed")
            time.sleep(config.LOBBY_POLL_SECONDS)

    def stop(self) -> None:
        self._stop.set()
        self._stop_event_bus()
        self._stop_gameflow_bus()
        self._stop_live_poller()
        self.stop_live_demo()

    def _tick(self) -> None:
        """The poll loop now only manages the LCU connection and phase, and
        owns the champ-select WebSocket listener's lifecycle. The heavy draft
        processing is event-driven (see ``_on_session``); polling here is just
        the connection watchdog plus an injection-retry safety net."""
        # Keep the scoring universe current with no manual trigger. Runs before
        # the LCU gate so a fresh install populates the DB at startup, even with
        # the League client closed (the sync only needs op.gg + Data Dragon).
        self._maybe_auto_full_sync()
        self._maybe_build_rag_index()
        self._refresh_system_status()

        if self.client is None or not self.client.is_alive():
            was_connected = self.client is not None
            self._stop_event_bus()
            self._stop_gameflow_bus()
            self.client = LCUClient.connect()
            if self.client is None:
                if was_connected:
                    log.warning("Lost connection to the League client")
                self.state.update("lcu", connected=False, phase="None", summoner="")
                return
            summoner = self.client.current_summoner() or {}
            self._summoner_id = summoner.get("summonerId", 0)
            self._my_puuid = summoner.get("puuid", "")
            self._my_riot_id = (summoner.get("gameName", "") or "",
                                summoner.get("tagLine", "") or "")
            name = summoner.get("displayName") or summoner.get("gameName") or ""
            self.state.update("lcu", connected=True, summoner=name)
            threading.Thread(target=self._refresh_champion_stats,
                             name="ag-champ-stats", daemon=True).start()
            if not self._catalog_lcu_supplemented:
                added = self.catalog.supplement_from_lcu(self.client)
                if added:
                    log.info("LCU catalog supplement: %d new item(s) added", added)
                # Reconvert always — catalog may have been supplemented in a
                # previous session while the cache was re-seeded since then.
                reconverted = self.store.reconvert_opgg_builds(self.catalog)
                if reconverted:
                    log.info("Re-converted %d build(s) with newly available items",
                             reconverted)
                self._catalog_lcu_supplemented = True
                # A fresh LCU connection means the network is up — prompt the
                # auto full-sync check to run on the next tick (it stays guarded
                # and only crawls op.gg if the patch actually moved).
                self._last_auto_sync_check = 0.0
            # Subscribe to gameflow phase pushes for instant transitions; the
            # seed below drives the first _handle_phase for the current phase.
            self._ensure_gameflow_bus()

        # Poll the phase as a safety net (and seed when the WS hasn't pushed yet);
        # the gameflow WS handles the same transition the instant it happens.
        phase = self.client.gameflow_phase()
        self._handle_phase(phase)
        # Proactively warm stale builds while idle in the client — never during a
        # live game, so the warm-up fetches don't compete with anything.
        if phase != "InProgress":
            self._maybe_warm_builds()

    def _handle_phase(self, phase: str) -> None:
        """Drive all phase-dependent subsystems (event bus, live poller, state
        clearing) for ``phase``. Invoked both by the gameflow WS push (instant)
        and by the poll-loop watchdog (safety net), so a lock serializes the two
        and the body stays idempotent."""
        with self._phase_lock:
            if self.client is None:
                return
            self.state.update("lcu", connected=True, phase=phase)

            # The live-game overlay poller only runs during the actual game.
            if phase != "InProgress":
                self._stop_live_poller()

            if phase == "InProgress":
                self._stop_event_bus()
                self._ensure_live_poller()
            elif phase == "ChampSelect":
                self._ensure_event_bus()
                self._clear_post_game()  # a new game starts — drop the last report
                # Resilience: the WebSocket only pushes *deltas*, so when it isn't
                # running (older client / blocked port) OR nothing has been published
                # yet this champ select, poll the current state so the dashboard
                # switches to Live Draft immediately — without waiting for a hover.
                bus_ok = self._event_bus and self._event_bus.is_running()
                if not bus_ok or self.state.snapshot().get("lobby") is None:
                    ctx = read_match_context(self.client, self.catalog,
                                             summoner_id=self._summoner_id)
                    if ctx:
                        self._enrich_roles(ctx)  # infer hidden roles (enemy + self)
                        self._publish_lobby(ctx, demo=False)
                        self._maybe_recommend(ctx)
                self._retry_injection_if_pending()
            elif phase == "Lobby":
                # Pre-game: keep the event bus up so lobby-scouting fires the moment
                # the premade roster changes; the draft views stay cleared.
                self._ensure_event_bus()
                self._clear_post_game()  # a new game starts — drop the last report
                self._reset_draft_state()
                if not self.state.snapshot().get("demo"):
                    self.state.set("lobby", None)
                    self.state.set("draft_intel", None)
                    self.state.set("recommendation", None)
                    self.state.set("draft_clock", None)
                    self.state.set("matchups", None)
                    self.state.set("callouts", None)
            elif phase in ("WaitingForStats", "PreEndOfGame", "EndOfGame"):
                # Post-game: keep the bus alive so the end-of-game stats block push
                # (and its seed) can trigger the auto-review. The post-game report is
                # left in place so it stays on screen through these phases.
                self._ensure_event_bus()
                self._reset_draft_state()
                self._clear_scout()
                if not self.state.snapshot().get("demo"):
                    self.state.set("lobby", None)
                    self.state.set("draft_intel", None)
                    self.state.set("recommendation", None)
                    self.state.set("draft_clock", None)
                    self.state.set("matchups", None)
                    self.state.set("callouts", None)
            elif phase in ("Matchmaking", "None"):
                self._stop_event_bus()
                self._reset_draft_state()
                self._clear_scout()
                if not self.state.snapshot().get("demo"):
                    self.state.set("lobby", None)
                    self.state.set("draft_intel", None)
                    self.state.set("recommendation", None)
                    self.state.set("draft_clock", None)
                    self.state.set("matchups", None)
                    self.state.set("callouts", None)

    # ------------------------------------------------- LCU event bus
    def _ensure_event_bus(self) -> None:
        """Start the multiplexed LCU event bus if it isn't already up, subscribed
        to both the champ-select session and the pre-game lobby topics over one
        connection. Idempotent across the Lobby → ChampSelect transition."""
        if self._event_bus and self._event_bus.is_running():
            return
        if self.client is None:
            return
        bus = LcuEventBus(self.client.creds)
        bus.subscribe(CHAMP_SELECT_TOPIC, self._on_session)
        bus.subscribe(LOBBY_TOPIC, self._on_lobby)
        bus.subscribe(EOG_TOPIC, self._on_eog)
        bus.start()
        self._event_bus = bus
        # The WS only delivers changes from here on, so seed the CURRENT champ
        # select / lobby state right now — otherwise the dashboard wouldn't
        # switch to Live Draft (or scout the premade) until the first event.
        try:
            session = self.client.get_json("/lol-champ-select/v1/session")
            if isinstance(session, dict):
                self._on_session(session, "Create")
        except Exception:
            log.debug("Initial champ-select seed failed", exc_info=True)
        try:
            lobby = self.client.get_json("/lol-lobby/v1/lobby")
            if isinstance(lobby, dict):
                self._on_lobby(lobby, "Create")
        except Exception:
            log.debug("Initial lobby seed failed", exc_info=True)
        try:
            eog = self.client.get_json("/lol-end-of-game/v1/eog-stats-block")
            if isinstance(eog, dict):
                self._on_eog(eog, "Create")
        except Exception:
            log.debug("Initial eog seed failed", exc_info=True)

    def _stop_event_bus(self) -> None:
        if self._event_bus is not None:
            self._event_bus.stop()
            self._event_bus = None

    # ------------------------------------------------- gameflow event bus
    def _ensure_gameflow_bus(self) -> None:
        """Start the always-on gameflow bus (while connected) so phase changes
        act instantly. Separate from ``_event_bus`` precisely because that one is
        torn down per phase — we must not miss the transition that ends a game."""
        if self._gameflow_bus and self._gameflow_bus.is_running():
            return
        if self.client is None:
            return
        bus = LcuEventBus(self.client.creds)
        bus.subscribe(GAMEFLOW_TOPIC, self._on_gameflow)
        bus.start()
        self._gameflow_bus = bus

    def _stop_gameflow_bus(self) -> None:
        if self._gameflow_bus is not None:
            self._gameflow_bus.stop()
            self._gameflow_bus = None

    def _on_gameflow(self, data: str | None, event_type: str) -> None:
        """Gameflow-phase push (bus thread): ``data`` is the new phase string
        (not a resource dict). Drive the transition immediately; the poll loop
        remains as a safety net for missed pushes."""
        if event_type == "Delete" or not isinstance(data, str) or not data:
            return
        if self.client is None:
            return
        log.debug("Gameflow phase push: %s", data)
        self._handle_phase(data)

    # --------------------------------------------------- pre-game lobby scout
    def _on_lobby(self, data: dict | None, event_type: str) -> None:
        """Event-bus callback (bus thread): the premade lobby roster changed.
        Scout every member whose puuid we can resolve. Best-effort."""
        if event_type == "Delete" or not isinstance(data, dict):
            return
        players = _scout_players_from_lobby(data)
        if players:
            self._maybe_scout(players)

    def _maybe_scout(self, players: list[dict]) -> None:
        """Dedup on the resolvable-puuid set and kick scouting off-thread. A
        static roster (no new puuids) is scouted only once; anonymized players
        (no puuid) never gate the signature, so they don't suppress a refresh."""
        resolvable = sorted(p["puuid"] for p in players if p.get("puuid"))
        if not resolvable:
            return  # nothing identifiable to scout (e.g. fully anonymized)
        sig = "|".join(resolvable)
        if sig == self._last_scout_sig:
            return
        self._last_scout_sig = sig
        threading.Thread(target=self._run_scout, args=(players,),
                         name="ag-lobby-scout", daemon=True).start()

    def _run_scout(self, players: list[dict]) -> None:
        """Fetch + fingerprint each resolvable player (cached per puuid) and
        publish the enriched scout roster. Runs on its own thread so a slow LCU
        history fetch never stalls the event bus."""
        if not self._scout_lock.acquire(blocking=False):
            return  # a scout pass is already in flight
        try:
            if self.client is None:
                return
            out: list[dict] = []
            for p in players:
                puuid = p.get("puuid")
                if not puuid:
                    out.append(self._hidden_card(p))
                    continue
                enriched = self._player_scout_cache.get(puuid)
                if enriched is None:
                    try:
                        games = scout_mod.recent_games_for_puuid(self.client, puuid)
                        fp = scout_mod.fingerprint(games)
                    except Exception:
                        log.debug("Scout fetch failed for a player", exc_info=True)
                        fp = scout_mod.PlayerFingerprint()
                    enriched = self._enrich_fingerprint(fp)
                    self._player_scout_cache[puuid] = enriched
                meta = self._player_meta(p)
                out.append({**enriched, **meta,
                            "autofill": scout_mod.autofill_read(
                                enriched.get("roles"), meta.get("position", ""))})
            self._apply_self_rank(out)
            self.state.set("scout", {"players": out, "ready": True, "at": time.time()})
            scouted = sum(1 for p in out if not p.get("hidden"))
            log.info("Lobby scout: %d player(s) profiled (%d hidden)",
                     scouted, len(out) - scouted)
        finally:
            self._scout_lock.release()

    def self_rank_summary(self) -> dict | None:
        """Public accessor for the local player's rank — the coach API uses it to
        grade against the player's own rank band instead of one global constant."""
        return self._self_rank_summary()

    def _self_rank_summary(self) -> dict | None:
        """The local player's own rank from the LCU, cached per scout session.
        Lets the live board show your rank even in custom/bot games (Spectator
        doesn't return those, so the Riot scout never fetches it). Best-effort."""
        if self._self_ranked is None and self.client is not None:
            try:
                from sylqon.lcu.ranked import current_ranked_summary
                self._self_ranked = current_ranked_summary(self.client) or {}
            except Exception:
                log.debug("self-rank fetch failed", exc_info=True)
                self._self_ranked = {}
        return self._self_ranked or None

    def _apply_self_rank(self, players: list[dict]) -> None:
        """Stamp the local player's own LCU rank onto their scout entry."""
        acct = self._self_rank_summary()
        if not acct:
            return
        for entry in players:
            if entry.get("is_self"):
                entry["rank"] = acct.get("rank", "") or entry.get("rank", "")
                entry["account"] = acct
                break

    def _hidden_card(self, p: dict) -> dict:
        return {"hidden": True, "games_analyzed": 0, **self._player_meta(p)}

    @staticmethod
    def _player_meta(p: dict) -> dict:
        return {"name": p.get("name", "") or "Hidden", "position": p.get("position", ""),
                "side": p.get("side", "ally"), "is_self": bool(p.get("is_self"))}

    def _enrich_fingerprint(self, fp: scout_mod.PlayerFingerprint) -> dict:
        """Resolve the id-based fingerprint's champion ids to display name+slug
        so the dashboard and the LLM prompt can read it directly."""
        d = fp.to_dict()
        for entry in d.get("champion_pool", []):
            self._name_slug(entry)
        if d.get("comfort"):
            self._name_slug(d["comfort"])
        return d

    def _name_slug(self, entry: dict) -> None:
        info = self.catalog.champion_by_key(entry.get("champion_id", 0)) or {}
        entry["champion"] = info.get("name", "")
        entry["slug"] = info.get("id", "")

    def _clear_scout(self) -> None:
        self._last_scout_sig = None
        self._player_scout_cache.clear()
        self._self_ranked = None   # re-read next session (LP/tier may have changed)
        self.state.set("scout", {"players": [], "ready": False, "at": None})

    # ----------------------------------------------- auto post-game review
    def _on_eog(self, data: dict | None, event_type: str) -> None:
        """Event-bus callback (bus thread): the end-of-game stats block appeared.
        Trigger the auto-review off-thread; the heavy DB + Ollama work is guarded
        and deduped by game id inside ``_run_post_game_review``."""
        if event_type == "Delete" or self.client is None:
            return
        threading.Thread(target=self._run_post_game_review,
                         name="ag-post-game", daemon=True).start()

    def _run_post_game_review(self) -> None:
        """Ingest the just-finished game, run the AI match review (graceful when
        Ollama is offline), and publish it to the ``post_game`` state. Deduped on
        the stored game id so repeated eog pushes/seeds review a game only once."""
        if not self._review_lock.acquire(blocking=False):
            return
        session = None
        try:
            from sylqon.ai.match_review import MatchReviewAnalyzer
            from sylqon.db import matches as match_store
            from sylqon.db import queries
            from sylqon.db.schema import MatchAnalysis
            from sylqon.db.session import get_session
            if self.client is None:
                return
            session = get_session()
            match_store.sync_recent_matches(session, self.client, limit=5)
            session.commit()
            rows = queries.recent_matches(session, 1)
            if not rows:
                return
            m = rows[0]
            if m.game_id == self._last_reviewed_game:
                return  # already reviewed this game
            self._last_reviewed_game = m.game_id
            match_dict = match_store.serialize_match(session, m)
            # Publish the match immediately; the analysis lands when Ollama returns.
            self.state.set("post_game", {"active": True, "match": match_dict,
                                         "analysis": None, "pending": True,
                                         "at": time.time()})
            result = MatchReviewAnalyzer(self.engine).analyze_match(
                match_store.match_to_analysis_input(session, m))
            if result is None:
                self.state.update("post_game", pending=False)
                log.info("Post-game review: Ollama offline — %s %s recorded "
                         "without analysis", match_dict["champion"], match_dict["result"])
                return
            if m.analysis is None:
                session.add(MatchAnalysis(
                    match_id=m.id, summary=result["summary"], strengths=result["strengths"],
                    weaknesses=result["weaknesses"], tips=result["tips"]))
                session.commit()
            self.state.set("post_game", {"active": True, "match": match_dict,
                                         "analysis": result, "pending": False,
                                         "at": time.time()})
            log.info("Auto post-game review ready: %s (%s)",
                     match_dict["champion"], match_dict["result"])
        except Exception:
            log.exception("Auto post-game review failed")
            if session is not None:
                session.rollback()
        finally:
            if session is not None:
                session.close()
            self._review_lock.release()

    def _clear_post_game(self) -> None:
        self._last_reviewed_game = None
        if self.state.snapshot().get("post_game", {}).get("active"):
            self.state.set("post_game", {"active": False})

    # ------------------------------------------------- live-game overlay poller
    def _ensure_live_poller(self) -> None:
        """Start the read-only Live Client Data poller (once) for this game."""
        if self._live_demo_thread is not None and self._live_demo_thread.is_alive():
            self.stop_live_demo()  # a real game preempts the simulated one
        if self._live_thread is not None and self._live_thread.is_alive():
            return
        self._live_stop.clear()
        self._was_in_game = True
        self._live_thread = threading.Thread(
            target=self._live_loop, name="ag-live", daemon=True)
        self._live_thread.start()
        log.info("Live game poller started")
        # Kick off Riot API scouting for all 10 players via Spectator + MATCH.
        puuid = self._riot_self_puuid()
        if puuid:
            threading.Thread(
                target=self._do_live_scout,
                args=(puuid,),
                name="ag-live-scout",
                daemon=True,
            ).start()
            # Scale mission difficulty to the player's own rank (best-effort).
            threading.Thread(
                target=self._apply_self_tier,
                args=(puuid,),
                name="ag-self-tier",
                daemon=True,
            ).start()
        else:
            log.info("Live scout skipped: no usable PUUID (set RIOT_SELF_PUUID)")

    def _apply_self_tier(self, puuid: str) -> None:
        """Resolve the player's ranked tier and scale mission goals to it. Best-
        effort: no API key / unranked / any failure leaves the 1.0 baseline."""
        try:
            from sylqon.riot.api import get_ranked_stats
            from sylqon.riot.scout import _solo_entry
            tier = (_solo_entry(get_ranked_stats(puuid)) or {}).get("tier", "")
            if tier:
                self._mission_engine.set_tier(tier)
                log.info("Mission difficulty scaled to rank: %s", tier)
        except Exception:
            log.debug("Self-tier resolution failed", exc_info=True)

    def _riot_self_puuid(self) -> str:
        """The PUUID for Riot API calls. The LCU's current-summoner puuid is
        normally the encrypted PUUID, but some clients hand back a short internal
        UUID that SPECTATOR-V5 rejects with 400. Resolution order:
          1. the LCU value, if it's already a full encrypted PUUID (>= 70 chars);
          2. the configured RIOT_SELF_PUUID override;
          3. ACCOUNT-V1 lookup by the LCU Riot ID (cached) — so the scout works
             out of the box with no manual config or .env in packaged builds."""
        lcu = self._my_puuid or ""
        if len(lcu) >= 70:
            return lcu
        if config.RIOT_SELF_PUUID:
            return config.RIOT_SELF_PUUID
        if self._resolved_puuid:
            return self._resolved_puuid
        game_name, tag_line = self._my_riot_id
        if game_name and tag_line and config.RIOT_API_KEY:
            try:
                from sylqon.riot.api import get_account_by_riot_id
                acct = get_account_by_riot_id(game_name, tag_line) or {}
                pu = acct.get("puuid", "")
                if len(pu) >= 70:
                    self._resolved_puuid = pu
                    log.info("Resolved encrypted PUUID via ACCOUNT-V1 for %s#%s",
                             game_name, tag_line)
                    return pu
            except Exception:
                log.warning("ACCOUNT-V1 PUUID resolution failed", exc_info=True)
        return lcu

    def _stop_live_poller(self) -> None:
        """Tear the poller down on game end and clear the overlay state."""
        if self._live_thread is None:
            return
        self._live_stop.set()
        self._live_thread = None
        self._mission_engine.tick(LiveGameState.none())  # clear active missions
        self.state.set("live", LiveGameState.none().to_dict())
        self.state.set("overlay", {"active": False, "role": "", "missions": [], "game": {}})
        self.state.set("matchups", None)
        self.state.set("callouts", None)
        log.info("Live game poller stopped")
        # The game just ended: generate the next batch of champion missions from
        # its post-game stats (off-thread — a slow Ollama call never blocks polls).
        self._was_in_game = False
        self._schedule_mission_generation()

    def _await_active_game(self, my_puuid: str, attempts: int = 18,
                           interval: float = 20.0) -> dict | None:
        """Poll SPECTATOR-V5 until the active game appears, then return it.

        Riot's spectator endpoint lags the actual game start by ~1-2 minutes, so
        the scout firing at poller start would otherwise get a 404 once and never
        run. Retry with a fixed interval (interruptible via ``_live_stop`` so it
        stops the instant the game ends) for up to ``attempts * interval`` seconds.
        Returns the game dict, or ``None`` if it never appears / the game ended."""
        from sylqon.riot.api import get_active_game_by_puuid
        for i in range(attempts):
            if self._live_stop.is_set():
                return None
            game = get_active_game_by_puuid(my_puuid)
            if isinstance(game, dict):
                if i:
                    log.info("Live scout: spectator game available after ~%ds",
                             int(i * interval))
                return game
            # interruptible sleep — returns immediately if the game ends
            if self._live_stop.wait(interval):
                return None
        return None

    def _do_live_scout(self, my_puuid: str) -> None:
        """Scout all 10 players via Spectator + MATCH APIs in two phases so the
        board fills in fast:

          Phase A (cheap, ~1-2s): rank + mastery + current-champ for everyone, in
            parallel. All 10 cards are pushed at once — the user sees the full
            roster immediately, with the deep stats still pending.
          Phase B (slow): the match-history fingerprint per player. Each player's
            deep read is streamed into its card the moment it resolves, rather
            than waiting for the slowest of the ten.

        Premade detection needs every player's shared games, so it runs as a
        final overlay once all of Phase B has completed. Runs on a daemon
        thread; never raises."""
        try:
            from sylqon.riot import api as riot_api
            from sylqon.riot import scout as riot_scout

            game = self._await_active_game(my_puuid)
            if not isinstance(game, dict):
                log.info("Live scout: spectator game not found (gave up after retries)")
                return
            participants = game.get("participants") or []

            me = next((p for p in participants if p.get("puuid") == my_puuid), None)
            my_team_id = me.get("teamId") if me else 100

            puuids = [p["puuid"] for p in participants if p.get("puuid")]
            if not puuids:
                return

            # ---- Phase A: rank + mastery for all 10, in parallel. -------------
            log.info("Live scout: phase 1 (rank/mastery) for %d players", len(puuids))
            accounts: dict[str, tuple[dict, list | None]] = {}
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(10, len(puuids))) as ex:
                futs = {ex.submit(riot_scout.scout_account, pu): pu for pu in puuids}
                for fut in concurrent.futures.as_completed(futs):
                    pu = futs[fut]
                    try:
                        accounts[pu] = fut.result()
                    except Exception:
                        log.debug("scout_account failed for %s…", pu[:8], exc_info=True)
                        accounts[pu] = ({}, None)

            # Build a thin card per player (no fingerprint yet) and show all 10.
            cards: dict[str, dict] = {}
            for p in participants:
                pu = p.get("puuid", "")
                account, _ = accounts.get(pu, ({}, None))
                cid = p.get("championId")
                cc = riot_scout.current_champ_stats(
                    None, (account or {}).get("mastery"), cid)
                # Fall back to a direct mastery lookup when the current champ is
                # outside the player's top-5 mastery (best-effort, never fatal).
                if cc.get("mastery_points") is None and cid:
                    try:
                        m = riot_api.get_mastery_by_champion(pu, cid)
                        if m:
                            cc["mastery_points"] = m.get("championPoints")
                            cc["mastery_level"] = m.get("championLevel")
                    except Exception:
                        log.debug("by-champion mastery lookup failed", exc_info=True)

                name = (p.get("riotId") or "").split("#")[0] or p.get("summonerName", "")
                cards[pu] = {
                    "games_analyzed": 0,
                    "deep_pending": True,   # match-history fingerprint still loading
                    "name": name,
                    "puuid": pu,
                    "champion_id": cid,
                    "rank": (account or {}).get("rank", ""),
                    "account": account or {},
                    "current_champ": cc,
                    "premade_group": None,
                    "side": "ally" if p.get("teamId") == my_team_id else "enemy",
                    "position": (p.get("teamPosition") or "").lower(),
                }

            self._on_live_scout(list(cards.values()), premade_groups=0)
            self._publish_live_matchups()  # early read: matchup + rank + experience

            # ---- Phase B: match-history fingerprint, streamed in per player. --
            log.info("Live scout: phase 2 (match history) for %d players", len(puuids))
            mastery_by_pu = {pu: acc[1] for pu, acc in accounts.items()}
            comatches: dict[str, dict] = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(riot_scout.scout_history, pu,
                                  mastery_by_pu.get(pu)): pu for pu in puuids}
                for fut in concurrent.futures.as_completed(futs):
                    pu = futs[fut]
                    try:
                        fp, cm = fut.result()
                    except Exception:
                        log.debug("scout_history failed for %s…", pu[:8], exc_info=True)
                        fp, cm = None, {}
                    comatches[pu] = cm or {}

                    card = cards.get(pu)
                    if card is None:
                        continue
                    patch: dict = {"deep_pending": False}
                    if fp and fp.games_analyzed > 0:
                        deep = fp.to_dict()
                        for pool_entry in deep.get("champion_pool", []):
                            self._name_slug(pool_entry)
                        if deep.get("comfort"):
                            self._name_slug(deep["comfort"])
                        # Now that we have recent games, refine current-champ —
                        # but keep the Phase-A mastery fallback if history can't.
                        prev_cc = card.get("current_champ") or {}
                        cc = riot_scout.current_champ_stats(
                            fp, (card.get("account") or {}).get("mastery"),
                            card.get("champion_id"))
                        if cc.get("mastery_points") is None:
                            cc["mastery_points"] = prev_cc.get("mastery_points")
                            cc["mastery_level"] = prev_cc.get("mastery_level")
                        patch.update(deep)
                        patch["current_champ"] = cc
                        # Off-role read: now that we know what they usually play,
                        # compare it to the role Spectator says they're on.
                        patch["autofill"] = scout_mod.autofill_read(
                            deep.get("roles"), card.get("position", ""))
                    # Stream just this player's deep read onto the board. (The
                    # local `card` is read-only here — Phase A appended its dict
                    # by reference into published state, so mutating it would let
                    # a polling reader see a half-applied update.)
                    self._patch_scout_players({pu: patch})

            # ---- Final overlay: premade groups from everyone's shared games. --
            groups = riot_scout.detect_premades(set(puuids), comatches)
            group_of = {pu: i for i, g in enumerate(groups) for pu in g}
            name_by_pu = {pu: c.get("name", "") for pu, c in cards.items()}
            premade_patches: dict[str, dict] = {}
            for pu in cards:
                g = group_of.get(pu)
                patch = {"premade_group": g}
                if g is not None:
                    patch["premade_partners"] = [
                        name_by_pu[x] for x in groups[g]
                        if x != pu and name_by_pu.get(x)
                    ]
                premade_patches[pu] = patch
            self._patch_scout_players(premade_patches, premade_groups=len(groups))
            self._publish_live_matchups()  # full read: form now folded in too
        except Exception:
            log.exception("_do_live_scout failed")

    # Riot-only fields that may be overlaid onto an ally's richer LCU fingerprint
    # without clobbering it (mirrors the overlay set in `_on_live_scout`).
    _SCOUT_OVERLAY_FIELDS = (
        "current_champ", "premade_group", "premade_partners",
        "rank", "account", "champion_id",
    )

    def _patch_scout_players(self, patches: dict[str, dict],
                             premade_groups: int | None = None) -> None:
        """Overlay per-player ``patches`` (keyed by puuid) onto the live scout
        board without re-running the LCU reconciliation in `_on_live_scout`.

        Used to *stream* Phase-B deep stats and premade groups onto the cards the
        Phase-A push already placed. A card still awaiting its match-history
        fingerprint carries ``deep_pending`` — those take the full patch. Cards
        without it are ally fingerprints sourced from the (richer) LCU champ-select
        scout, so only the Riot-only fields are overlaid; their champion pool is
        preserved. Entries not present in ``patches`` pass through untouched."""
        current = self.state.snapshot().get("scout") or {}
        players: list[dict] = current.get("players") or []
        merged: list[dict] = []
        for p in players:
            patch = patches.get(p.get("puuid", ""))
            if not patch:
                merged.append(p)
                continue
            new = dict(p)
            if p.get("deep_pending"):
                new.update(patch)               # Riot-only card → full overlay
            else:                               # LCU-rich ally → keep fingerprint
                for k in self._SCOUT_OVERLAY_FIELDS:
                    if k in patch:
                        new[k] = patch[k]
                new["deep_pending"] = False
            merged.append(new)
        scout = {**current, "players": merged, "ready": True, "at": time.time()}
        if premade_groups is not None:
            scout["premade_groups"] = premade_groups
        self.state.set("scout", scout)

    def _on_live_scout(self, players: list[dict], premade_groups: int = 0) -> None:
        """Merge Riot-scouted players into the scout state. Existing ally LCU
        fingerprints are kept (they're richer), but the Riot-only fields — rank,
        account summary, premade group, and current-champ stats — are overlaid
        onto them so the live board has the full read for everyone.

        Allies are matched to their existing LCU entry by puuid, falling back to
        riot-name when the puuids disagree: champ select / current-summoner can
        hand back a short internal id while SPECTATOR-V5 returns the encrypted
        puuid, so a puuid-only merge would never collapse the two sources and the
        board would show 5 + 10 = 15 cards instead of 10."""
        current = self.state.snapshot().get("scout") or {}
        existing: list[dict] = current.get("players") or []
        by_puuid: dict[str, dict] = {
            p.get("puuid", ""): p for p in existing if p.get("puuid")
        }

        def _name_key(p: dict) -> str:
            return (p.get("name") or "").strip().casefold()

        by_name: dict[str, dict] = {
            _name_key(p): p for p in existing if _name_key(p)
        }

        merged: list[dict] = []
        seen_puuids: set[str] = set()   # spectator puuids re-added this pass
        consumed: set[int] = set()      # id() of existing entries folded into a row
        for p in players:
            pu = p.get("puuid") or ""
            if pu:
                seen_puuids.add(pu)
            base = by_puuid.get(pu)
            if base is None and p.get("side") == "ally":
                base = by_name.get(_name_key(p))  # puuid-format mismatch fallback
            if base is not None and p.get("side") == "ally":
                # Keep the richer LCU fingerprint; overlay the Riot-only fields and
                # adopt the spectator puuid so premade lookups stay consistent.
                consumed.add(id(base))
                merged.append({
                    **base,
                    "puuid": pu or base.get("puuid", ""),
                    "rank": base.get("rank") or p.get("rank", ""),
                    "account": p.get("account") or base.get("account"),
                    "current_champ": p.get("current_champ"),
                    "premade_group": p.get("premade_group"),
                    "premade_partners": p.get("premade_partners"),
                    "champion_id": p.get("champion_id", base.get("champion_id")),
                })
            else:
                merged.append(p)
        # Preserve existing entries the spectator never covered — a hidden ally, or
        # every ally when there's no Riot API key / it's a custom game (the LCU
        # champ-select scout is then the only ally data we have).
        for p in existing:
            if id(p) in consumed:
                continue
            if (p.get("puuid") or "") in seen_puuids:
                continue  # spectator already re-added this player (e.g. an enemy)
            merged.append(p)
        self.state.set("scout", {**current, "players": merged,
                                  "premade_groups": premade_groups,
                                  "ready": True, "at": time.time()})
        enemies = sum(1 for p in merged if p.get("side") == "enemy"
                      and p.get("games_analyzed", 0) > 0)
        log.info("Live scout: %d enemy profiled, %d premade group(s)",
                 enemies, premade_groups)

    def _live_loop(self) -> None:
        """Poll the Live Client Data API at a conservative cadence and publish a
        normalized snapshot. READ-ONLY: GET only, never writes to the client."""
        while not self._live_stop.is_set():
            try:
                raw = self._live_client.get_all_game_data()
                my_role = self.last_ctx.my_role if self.last_ctx else ""
                snap = parse_live_state(raw, my_role=my_role)
                self.state.set("live", snap.to_dict())
                if snap.role or snap.champion:
                    self._mission_engine.set_context(snap.role, snap.champion)
                self.state.set("overlay", self._mission_engine.tick(snap))
            except Exception:
                log.debug("Live poll tick failed", exc_info=True)
            self._live_stop.wait(config.LIVE_POLL_SECONDS)

    def live_snapshot(self) -> dict:
        """Fresh read-only snapshot of the live game (for the debug endpoint).
        Returns the no-game sentinel when port 2999 isn't responding."""
        raw = self._live_client.get_all_game_data()
        my_role = self.last_ctx.my_role if self.last_ctx else ""
        return parse_live_state(raw, my_role=my_role).to_dict()

    def _on_mission_resolved(self, mission, result: str) -> None:
        """Engine callback (live-poller thread): persist the resolved mission and
        award points — to the champion being played (mastery) and the account
        aggregate. Best-effort — never breaks the poll loop."""
        from sylqon.db.session import get_session
        from sylqon.livegame.progression import ProgressionService
        session = get_session()
        try:
            summoner = (self.state.snapshot().get("lcu") or {}).get("summoner", "")
            svc = ProgressionService()
            profile = svc.ensure_profile(session, summoner)
            champion_id = self._resolve_champion_id(session, self._mission_engine.champion)
            svc.record_resolution(session, profile, mission, result,
                                  champion_id=champion_id,
                                  game_session=self._mission_engine.session_id or "")
            session.commit()
        except Exception:
            log.exception("Progression update failed")
            session.rollback()
        finally:
            session.close()

    def _resolve_champion_id(self, session, champion: str) -> int | None:
        """Map a champion display name / slug (from the live state or draft) to a
        ``Champion.id`` via the catalog's Riot key. Returns None when unknown."""
        if not champion:
            return None
        from sylqon.db.schema import Champion
        # live API may hand us the display name ("Miss Fortune") or the slug.
        info = self.catalog.champion_by_name(champion) or self.catalog.champion_by_slug(champion)
        if not info:
            return None
        try:
            riot_key = int(info["key"])
        except (KeyError, TypeError, ValueError):
            return None
        row = session.query(Champion).filter_by(riot_key=riot_key).first()
        return row.id if row else None

    def _champion_mission_source(self, role: str, champion: str) -> list:
        """Engine hook (live-poller thread): the champion's pending AI mission
        queue as live Mission templates. DB-backed, so it lives here and not in
        the DB-free engine. Empty list => engine uses the static role catalog."""
        from sylqon.db.session import get_session
        from sylqon.livegame import champion_missions
        try:
            session = get_session()
        except Exception:
            return []
        try:
            cid = self._resolve_champion_id(session, champion)
            if cid is None:
                return []
            return champion_missions.load_pending(session, cid, role)
        except Exception:
            log.debug("champion mission source failed", exc_info=True)
            return []
        finally:
            session.close()

    def _schedule_mission_generation(self) -> None:
        """Kick off post-game per-champion mission generation off-thread."""
        threading.Thread(target=self._generate_champion_missions,
                         name="ag-mission-gen", daemon=True).start()

    def _generate_champion_missions(self) -> None:
        """After a game ends: pull its post-game stats and top the just-played
        champion's mission queue back up to the target. Guarded so overlapping
        game-end transitions can't double-generate."""
        if not self._mission_gen_lock.acquire(blocking=False):
            return
        try:
            champ = self.last_ctx.my_champion if self.last_ctx else ""
            role = self.last_ctx.my_role if self.last_ctx else ""
            if not champ or self.client is None:
                return
            from sylqon.db.matches import sync_recent_matches
            from sylqon.db.session import get_session
            from sylqon.livegame import champion_missions
            from sylqon.livegame.progression import ProgressionService
            session = get_session()
            try:
                sync_recent_matches(session, self.client, limit=5)
                cid = self._resolve_champion_id(session, champ)
                if cid is None:
                    return
                ProgressionService().bump_games_played(session, cid)
                champion_missions.topup(
                    session, cid, champ, role, self.engine,
                    game_session=self._mission_engine.session_id or "")
                session.commit()
            except Exception:
                log.exception("Champion mission generation failed")
                session.rollback()
            finally:
                session.close()
        finally:
            self._mission_gen_lock.release()

    def reset_overlay(self) -> None:
        """Clear in-flight missions + the published overlay state (debug reset)."""
        self._mission_engine.active = []
        self._mission_engine.session_id = None
        self.state.set("overlay", {"active": False, "role": "", "missions": [], "game": {}})

    # ------------------------------------------------------- live demo mode
    def start_live_demo(self, role: str = "") -> dict:
        """Drive the overlay from a synthetic game so it can be tested without
        launching League. No real client interaction whatsoever."""
        if self._live_demo_thread is not None and self._live_demo_thread.is_alive():
            return {"ok": True, "detail": "live demo already running"}
        self._live_demo_role = role or (self.last_ctx.my_role if self.last_ctx else "") or "bottom"
        self._mission_engine.set_role(self._live_demo_role)
        self._live_demo_stop.clear()
        self._live_demo_thread = threading.Thread(
            target=self._live_demo_loop, name="ag-live-demo", daemon=True)
        self._live_demo_thread.start()
        log.info("Live demo started (role=%s)", self._live_demo_role)
        return {"ok": True, "detail": f"live demo started ({self._live_demo_role})"}

    def stop_live_demo(self) -> dict:
        if self._live_demo_thread is not None:
            self._live_demo_stop.set()
            self._live_demo_thread = None
        self._mission_engine.tick(LiveGameState.none())
        self.state.set("live", LiveGameState.none().to_dict())
        self.state.set("overlay", {"active": False, "role": "", "missions": [], "game": {}})
        return {"ok": True, "detail": "live demo stopped"}

    def _live_demo_loop(self) -> None:
        from sylqon.livegame.demo import fake_live_state
        start = time.monotonic()
        while not self._live_demo_stop.is_set():
            try:
                snap = fake_live_state(time.monotonic() - start, role=self._live_demo_role)
                self.state.set("live", snap.to_dict())
                self._mission_engine.set_context(snap.role, snap.champion)
                self.state.set("overlay", self._mission_engine.tick(snap))
            except Exception:
                log.debug("Live demo tick failed", exc_info=True)
            self._live_demo_stop.wait(config.LIVE_POLL_SECONDS)

    def _reset_draft_state(self) -> None:
        self._last_injected_fp = None
        self._last_reco_fp = None
        self._last_display_sig = None
        self._last_trigger_sig = None
        self.last_matchup = None
        self.last_lane_plan = None
        # Clear the sticky injection flag so the NEXT champ select starts in the
        # live-draft view. Without this, a prior game's status="ok" would make the
        # dashboard skip champ select and jump straight to the post-lock build.
        self.state.set("injection", {"status": "idle", "at": None, "detail": ""})

    def _on_session(self, data: dict | None, event_type: str) -> None:
        """WebSocket callback (runs on the listener thread). Two levels of state
        diffing keep this cheap: a display-signature gate discards pure timer
        ticks before any parsing, and a trigger-signature gate keeps Ollama
        asleep until a champion actually locks in or it becomes our turn."""
        if event_type == "Delete" or not isinstance(data, dict):
            return
        # Countdown for the live-draft UI: published on every push (~1/sec),
        # bypassing the display-signature gate below so the timer never stalls.
        self.state.set("draft_clock", parse_timer(data))
        sig = display_signature(data)
        if sig == self._last_display_sig:
            return  # timer tick / nothing visible changed — ignore entirely
        self._last_display_sig = sig

        ctx = read_match_context(self.client, self.catalog, session=data,
                                 summoner_id=self._summoner_id)
        if not ctx:
            return
        self._enrich_roles(ctx)  # infer hidden enemy roles → resurrect lane layer
        self._publish_lobby(ctx, demo=False)  # UI follows every visible change

        # Scout teammates whose identity champ select exposes (ranked solo
        # anonymizes enemies, so this is realistically our own team).
        players = _scout_players_from_session(data)
        if players:
            self._maybe_scout(players)

        trig = ctx.trigger_signature()
        if trig == self._last_trigger_sig:
            return  # display changed (e.g. spell swap) but no lock / turn flip
        self._last_trigger_sig = trig
        log.info("Draft trigger: locks/turn changed — recomputing")

        # Suggestion runs as soon as picks lock; the loadout is only injected
        # once the WHOLE lobby has locked, so we import against the final comp.
        self._maybe_recommend(ctx)
        if ctx.all_locked and ctx.fingerprint != self._last_injected_fp:
            self._do_injection(ctx)

    def _retry_injection_if_pending(self) -> None:
        """Poll-loop safety net: re-attempt injection if the lobby is fully
        locked but a prior attempt was partial (e.g. spells need an active
        champ select). No-op while an injection is already underway."""
        ctx = self.last_ctx
        if not ctx or not ctx.all_locked:
            return
        if ctx.fingerprint == self._last_injected_fp:
            return
        self._do_injection(ctx)

    def _enrich_roles(self, ctx: MatchContext) -> None:
        """Fill champ-select roles Riot hides (chiefly the enemy team, whose
        ``assignedPosition`` is not exposed) via op.gg-prior role inference, so
        the lane layer resolves a real lane opponent instead of degrading to
        nothing. Best-effort and in place; only ever fills an EMPTY role, never
        overrides a real ``assignedPosition``."""
        needs_self = not ctx.my_role_assigned and bool(ctx.my_champion)
        if not needs_self and not any(not p.role for p in (*ctx.enemies, *ctx.allies)):
            return
        try:
            from sylqon.db.session import get_session
            session = get_session()
        except Exception:
            return
        try:
            filled = (role_infer.enrich_roles(session, ctx.enemies)
                      + role_infer.enrich_roles(session, ctx.allies))
            if filled:
                log.info("Role inference filled %d hidden champ-select role(s)", filled)
            # The local player's own lane can be hidden too (blind pick). Infer it
            # from the champion so the loadout targets the right lane instead of
            # the blind "middle" default that produced no usable build.
            if needs_self:
                got = role_infer.infer_self_role(session, ctx.my_champion, ctx.allies)
                if got and got[0]:
                    log.info("Inferred hidden self role: %s -> %s (conf %.2f)",
                             ctx.my_champion, got[0], got[1])
                    ctx.my_role = got[0]
                    ctx.my_role_assigned = True
        finally:
            session.close()

    def _do_injection(self, ctx: MatchContext) -> None:
        """Compile + inject the final loadout off-thread so a slow Ollama call
        never stalls the WebSocket event pump. Guarded so only one injection
        runs at a time."""
        if self.client is None or not ctx.my_champion_id:
            return
        if not self._inject_lock.acquire(blocking=False):
            return  # an injection is already in flight

        def work() -> None:
            try:
                final = self.compile_loadout(ctx)
                if Injector(self.client).inject(final, ctx.summoner_id, ctx.my_champion_id):
                    self._last_injected_fp = ctx.fingerprint
                    self.store.track_champion(ctx.my_champion, ctx.my_role)
                    self.state.update("injection", status="ok", at=time.time(),
                                      detail=f"auto-injected for {ctx.my_champion}")
                else:
                    self.state.update("injection", status="partial", at=time.time(),
                                      detail="injection incomplete; retrying")
            except Exception:
                log.exception("Auto-injection failed")
            finally:
                self._inject_lock.release()

        threading.Thread(target=work, name="lcu-injection", daemon=True).start()

    def _refresh_system_status(self) -> None:
        self.state.update(
            "ollama", available=self.engine.available(), model=self.engine.model,
        )
        stats = self.store.stats()
        self.state.update(
            "cache",
            patch=self.catalog.patch, short_patch=self.catalog.short_patch,
            builds=stats["builds"], last_sync=stats["last_sync"],
        )

    # ------------------------------------------------------------- compile
    def _publish_lobby(self, ctx: MatchContext, demo: bool) -> None:
        my_info = self.catalog.champion_by_key(ctx.my_champion_id) or {}
        counters, synergies = self._pick_intel(ctx)
        enemies = []
        for e in ctx.enemies:
            d = serialize_enemy(e, self.catalog)
            if e.locked and counters.get(e.champion_id):
                d["counters"] = counters[e.champion_id]
            enemies.append(d)
        allies = []
        for a in ctx.allies:
            d = serialize_enemy(a, self.catalog)
            if a.locked and synergies.get(a.champion_id):
                d["synergies"] = synergies[a.champion_id]
            allies.append(d)
        self.state.set("lobby", {
            "my_champion": ctx.my_champion,
            "my_slug": my_info.get("id", ""),
            "my_role": ctx.my_role,
            "locked": ctx.locked,
            "all_locked": ctx.all_locked,
            "my_turn": ctx.my_turn,
            "enemies": enemies,
            "allies": allies,
            "bans": ctx.ban_slots,
            "threat_summary": ctx.team_threat_summary(),
            "ally_summary": self._ally_summary(ctx),
            "active_pick": ({"side": ctx.active_pick_side, "index": ctx.active_pick_index}
                            if ctx.active_pick_side else None),
        })
        self.state.set("demo", demo)
        self.last_ctx = ctx
        try:
            self.state.set("draft_intel", self._draft_intel(ctx))
        except Exception:
            log.debug("Draft-intel computation failed", exc_info=True)
            self.state.set("draft_intel", None)
        try:
            ally, enemy = self._champ_select_lane_cards(ctx)
            self._publish_matchups(ally, enemy, source="draft")
        except Exception:
            log.debug("Lane-matchup computation failed", exc_info=True)
        self._publish_callouts()

    # ------------------------------------------------------- lane matchups
    # Edge per lane (champion counter + form + rank + experience) published to
    # ``state["matchups"]``; the Players-tab lane ladders render it directly.
    _MATCHUP_ROLES = ("top", "jungle", "middle", "bottom", "utility")

    def _publish_matchups(self, ally_by_role: dict, enemy_by_role: dict,
                          source: str) -> None:
        """Blend the lane cards into per-role edges (best-effort DB matchup
        lookup) and publish. A DB failure degrades to a matchup-less blend rather
        than dropping the read entirely."""
        if not ally_by_role and not enemy_by_role:
            self.state.set("matchups", None)
            return
        roles = list(self._MATCHUP_ROLES)
        session = None
        try:
            from sylqon.db.session import get_session
            session = get_session()
            fn = self._matchup_fn(session)
            by_role = lane_matchup.compute_lanes(ally_by_role, enemy_by_role, fn, roles)
        except Exception:
            log.debug("lane-matchup DB pass failed; blending without matchups",
                      exc_info=True)
            by_role = lane_matchup.compute_lanes(
                ally_by_role, enemy_by_role, lambda a, e, r: None, roles)
        finally:
            if session is not None:
                session.close()
        self.state.set("matchups",
                       {"by_role": by_role, "source": source, "at": time.time()})

    def _matchup_fn(self, session):
        """DB-backed matchup lookup: two Riot champion keys + a role → the stored
        ``{advantage, games}`` head-to-head (or ``None``). Riot key → DB id
        resolution is cached across the five lane calls."""
        from sylqon.db import queries
        from sylqon.db.schema import Champion
        id_cache: dict[int, int | None] = {}

        def _db_id(riot_key) -> int | None:
            key = int(riot_key)
            if key not in id_cache:
                row = session.query(Champion).filter_by(riot_key=key).first()
                id_cache[key] = row.id if row else None
            return id_cache[key]

        def fn(a_key, e_key, role):
            a_id, e_id = _db_id(a_key), _db_id(e_key)
            if not a_id or not e_id:
                return None
            adv = queries.counter_map(session, a_id, role, [e_id]).get(e_id)
            if adv is None:
                return None
            games = queries.counter_games_map(session, a_id, role, [e_id]).get(e_id)
            return {"advantage": adv, "games": games}

        return fn

    @staticmethod
    def _structured_rank(sp: dict | None) -> dict | None:
        """Extract ``{tier, division, label}`` from a scout card's solo-queue
        account block, or ``None`` when the rank isn't known."""
        solo = ((sp or {}).get("account") or {}).get("solo")
        if not solo or not solo.get("tier"):
            return None
        return {"tier": solo.get("tier"), "division": solo.get("division"),
                "label": solo.get("label") or (sp or {}).get("rank")}

    def _champ_select_lane_cards(self, ctx: MatchContext) -> tuple[dict, dict]:
        """Lane cards from the draft: ally picks (with form/rank folded in from the
        current scout snapshot, matched by role) and locked enemy champions. Enemy
        fingerprints aren't available in champ select (Riot anonymizes them), so
        their cards carry the champion only — the matchup signal still works."""
        scout = self.state.snapshot().get("scout") or {}
        ally_scout_by_role: dict = {}
        for p in scout.get("players") or []:
            if p.get("hidden") or p.get("side") == "enemy":
                continue
            if p.get("position"):
                ally_scout_by_role.setdefault(p["position"], p)

        ally_by_role: dict = {}
        picks: list[tuple[str, int, str]] = []
        if ctx.my_champion_id and ctx.my_role:
            picks.append((ctx.my_role, ctx.my_champion_id, ctx.my_champion))
        for a in ctx.allies:
            if a.locked and a.role and a.champion_id:
                picks.append((a.role, a.champion_id, a.name))
        for role, cid, cname in picks:
            sp = ally_scout_by_role.get(role) or {}
            ally_by_role.setdefault(role, {
                "champion_id": cid, "champion": cname, "role": role,
                "name": sp.get("name") or cname,
                "recent_form": sp.get("recent_form"),
                "rank": self._structured_rank(sp),
                "current_champ": sp.get("current_champ"),
            })

        enemy_by_role: dict = {}
        for e in ctx.enemies:
            if e.locked and e.role and e.champion_id:
                enemy_by_role.setdefault(e.role, {
                    "champion_id": e.champion_id, "champion": e.name,
                    "role": e.role, "name": e.name,
                })
        return ally_by_role, enemy_by_role

    def _live_lane_cards(self) -> tuple[dict, dict]:
        """Lane cards from the in-game scout roster, where both teams' champion
        ids, roles and fingerprints are known (Spectator reveals every puuid)."""
        scout = self.state.snapshot().get("scout") or {}
        ally_by_role: dict = {}
        enemy_by_role: dict = {}
        for p in scout.get("players") or []:
            if p.get("hidden"):
                continue
            cid = p.get("champion_id")
            role = p.get("position")
            if not cid or not role:
                continue
            info = self.catalog.champion_by_key(cid) or {}
            card = {
                "champion_id": cid, "champion": info.get("name") or "", "role": role,
                "name": p.get("name") or info.get("name") or "",
                "recent_form": p.get("recent_form"),
                "rank": self._structured_rank(p),
                "current_champ": p.get("current_champ"),
            }
            target = enemy_by_role if p.get("side") == "enemy" else ally_by_role
            target.setdefault(role, card)
        return ally_by_role, enemy_by_role

    def _publish_live_matchups(self) -> None:
        """Recompute lane edges from the current in-game scout roster. Best-effort;
        called as scout phases stream in, so it must never raise."""
        try:
            ally, enemy = self._live_lane_cards()
            self._publish_matchups(ally, enemy, source="live")
        except Exception:
            log.debug("live lane-matchup computation failed", exc_info=True)
        self._publish_callouts()

    # ------------------------------------------------------ coaching callouts
    def _callout_cards(self) -> list[dict]:
        """Scout cards enriched with what the callout generators need: the resolved
        champion name, its damage type and threat tags, plus the live score when a
        game is running. Champ-select enemies (anonymized, so absent from the
        scout) are added from the draft picks so champion-driven advice — the
        itemization read especially — still works pre-game."""
        from sylqon.lcu.lobby import _damage_type, _threats
        snap = self.state.snapshot()
        live_by_name: dict[str, dict] = {}
        for r in ((snap.get("live") or {}).get("roster") or []):
            if r.get("name"):
                live_by_name[r["name"].strip().lower()] = r

        cards: list[dict] = []
        enemy_roles_seen: set[str] = set()
        for p in ((snap.get("scout") or {}).get("players") or []):
            if p.get("hidden"):
                continue
            info = self.catalog.champion_by_key(p.get("champion_id") or 0) or {}
            champ = info.get("name") or ""
            live = live_by_name.get((p.get("name") or "").strip().lower(), {})
            role = p.get("position") or ""
            if (p.get("side") or "ally") == "enemy" and role:
                enemy_roles_seen.add(role)
            cards.append({
                **p, "role": role, "champion": champ,
                "damage_type": _damage_type(info) if info else "",
                "threats": _threats(champ) if champ else [],
                "kills": live.get("kills"), "deaths": live.get("deaths"),
                "assists": live.get("assists"),
            })

        # Champ select: the enemy roster exists only as draft picks.
        for e in ((snap.get("lobby") or {}).get("enemies") or []):
            role, name = e.get("role") or "", e.get("name") or ""
            if not name or (role and role in enemy_roles_seen):
                continue
            info = self.catalog.champion_by_name(name) or {}
            cards.append({
                "name": name, "champion": name, "role": role, "side": "enemy",
                "champion_id": e.get("champion_id"),
                "damage_type": _damage_type(info) if info else "",
                "threats": _threats(name),
            })
        return cards

    def _publish_callouts(self) -> None:
        """Deterministic, evidence-bearing coaching callouts for the Players tab.
        Best-effort — a failure here must never disturb scouting."""
        try:
            my_role = self.last_ctx.my_role if self.last_ctx else ""
            cards = self._callout_cards()
            items = player_callouts.build_callouts(cards, my_role=my_role)
            self.state.set("callouts", {"items": items, "at": time.time()})
        except Exception:
            log.debug("callout computation failed", exc_info=True)

    def _pick_intel(self, ctx: MatchContext) -> tuple[dict, dict]:
        """Per-locked-pick Top-3 lists: counters for each revealed enemy and
        synergies for each locked ally, ranked across the WHOLE role roster (every
        champion that plays the lane), not just the player's pool. Tag heuristic
        floor + optional op.gg DB booster, minus anything already taken or banned.
        Returns ``({enemy_id: [...]}, {ally_id: [...]})``; best-effort, never
        raises."""
        session = None
        try:
            from sylqon.db.session import get_session
            session = get_session()
        except Exception:
            session = None
        try:
            from sylqon.ai.pick_prompt import build_candidates
            from sylqon.analysis import pairwise
            pool = self._role_universe(ctx.my_role, session)
            candidates = build_candidates(ctx, pool, self.catalog)
            excluded = ({ctx.my_champion}
                        | {self.catalog.champion_name(cid) for cid in ctx.bans})
            candidates = [c for c in candidates if c["name"] not in excluded]
            for c in candidates:
                c["slug"] = (self.catalog.champion_by_name(c["name"]) or {}).get("id", "")
            if not candidates:
                return {}, {}
            counters = {
                e.champion_id: pairwise.rank_counters_for_enemy(
                    e, candidates, session=session, role=ctx.my_role)
                for e in ctx.enemies if e.locked
            }
            synergies = {
                a.champion_id: pairwise.rank_synergies_for_ally(
                    a, candidates, session=session, role=ctx.my_role)
                for a in ctx.allies if a.locked
            }
            return counters, synergies
        except Exception:
            log.debug("pick-intel failed", exc_info=True)
            return {}, {}
        finally:
            if session is not None:
                session.close()

    def _role_universe(self, role: str, session) -> list[str]:
        """Every champion that plays ``role`` (op.gg lane-meta) for overall
        counter/synergy ranking — independent of the player's curated pool. Falls
        back to the buildable set when the DB roster isn't available yet (no sync
        / no session)."""
        if session is not None:
            try:
                from sylqon.db import queries
                names = [c.name for c in queries.champions_for_role(session, role)]
                if names:
                    return names
            except Exception:
                log.debug("role-universe DB lookup failed", exc_info=True)
        return self.store.buildable_for_role(role)

    def _ally_summary(self, ctx: MatchContext) -> dict:
        """Damage / threat profile of the player's own team (allies + the local
        champion), mirroring the enemy threat summary for an at-a-glance read."""
        from sylqon.lcu.lobby import _damage_type, _threats, summarize_team
        team = list(ctx.allies)
        if ctx.my_champion_id:
            mi = self.catalog.champion_by_key(ctx.my_champion_id) or {}
            team.append({"damage_type": _damage_type(mi),
                         "threats": _threats(ctx.my_champion),
                         "tags": mi.get("tags", [])})
        return summarize_team(team)

    # --------------------------------------------------------- draft intel
    def _draft_intel(self, ctx: MatchContext) -> dict:
        """Network-free read of the live draft: enemy/ally composition archetype,
        counter-pick timing, flex-pick warnings and ban suggestions. Recomputed
        on every visible draft change (cheap; no Ollama)."""
        my_pick = None
        if ctx.my_champion_id:
            info = self.catalog.champion_by_key(ctx.my_champion_id) or {}
            from sylqon.lcu.lobby import _damage_type, _threats
            my_pick = {"name": ctx.my_champion, "tags": info.get("tags", []),
                       "damage_type": _damage_type(info),
                       "threats": _threats(ctx.my_champion)}
        ally_picks = list(ctx.allies) + ([my_pick] if my_pick else [])
        enemy_comp = draft_intel.classify_comp(ctx.enemies)
        ally_comp = draft_intel.classify_comp(ally_picks)
        return {
            "enemy_comp": enemy_comp,
            "ally_comp": ally_comp,
            "balance": draft_intel.draft_balance(
                ally_comp, enemy_comp,
                self._ally_summary(ctx), ctx.team_threat_summary()),
            "counter_pick": draft_intel.counter_pick_advice(ctx),
            # Tempo vs scaling read — the timing axis that dictates the macro plan.
            "tempo": power_curve.tempo_read(ally_picks, ctx.enemies),
            "ban_now": ctx.my_ban_turn,
            "flex_warnings": self._flex_warnings(ctx),
            "ban_suggestions": self._ban_suggestions(ctx),
            "bans": [self.catalog.champion_name(cid) for cid in ctx.bans
                     if self.catalog.champion_name(cid)],
        }

    def _flex_warnings(self, ctx: MatchContext) -> list[dict]:
        """Revealed enemies that can play more than one lane — their final role
        (and thus the matchup) is not yet settled. Each carries the inferred lane
        and a confidence: when the role inference is a genuine toss-up (below
        ``FLEX_CONFIDENCE``) the entry is flagged ``tentative`` so downstream reads
        widen rather than commit to a single lane opponent (F4c). Best-effort
        against the DB."""
        from sylqon.db.schema import Champion
        from sylqon.db.session import get_session
        out: list[dict] = []
        try:
            session = get_session()
        except Exception:
            return out
        try:
            confidences = role_infer.infer_enemy_roles(session, ctx.enemies)
            for e in ctx.enemies:
                champ = session.query(Champion).filter_by(riot_key=e.champion_id).first()
                roles = list(champ.roles) if champ and champ.roles else []
                if len(roles) > 1:
                    conf = confidences.get(e.champion_id, (None, 1.0))[1]
                    out.append({
                        "name": e.name,
                        "slug": (self.catalog.champion_by_key(e.champion_id) or {}).get("id", ""),
                        "roles": roles,
                        "assigned": e.role,
                        "confidence": round(conf, 2),
                        "tentative": conf < role_infer.FLEX_CONFIDENCE,
                    })
        finally:
            session.close()
        return out

    def _ban_suggestions(self, ctx: MatchContext, limit: int = 3) -> list[dict]:
        """Team-wide, multi-factor ban list. Gathers meta threats across ALL five
        lanes (not just the player's), then scores each by meta strength, how hard
        it beats the player's pool, how contested it is, and whether it flexes —
        labelling every suggestion a **power** ban (meta-warping, deny it to
        anyone), a **personal** ban (specifically beats your pool) or a **meta**
        ban. Degrades gracefully: pure meta when counter data is thin, [] when no
        source is available.

        meta_report.json is the primary source, but it is never written by the app
        (only shipped/seeded), so packaged builds fall back to the synced DB tier
        list per lane — the same data the Patch Meta panel uses."""
        meta = self._meta_positions()
        # Fold every lane's meta rows into one candidate map, tracking which lanes
        # each champion appears in (≥2 → a flex threat) and keeping its strongest
        # (lowest-tier) row as the primary read.
        cand: dict[str, dict] = {}
        for role in role_infer.ROLES:
            for r in (meta.get(role) or self._db_role_rows(role)):
                name = r.get("champion", "")
                if not name:
                    continue
                cur = cand.get(name)
                if cur is None:
                    cand[name] = {"row": r, "roles": {role}, "tier": r.get("tier")}
                else:
                    cur["roles"].add(role)
                    if _tier_num(r.get("tier")) < _tier_num(cur["tier"]):
                        cur["row"], cur["tier"] = r, r.get("tier")
        if not cand:
            return []

        taken = ({e.name for e in ctx.enemies} | {a.name for a in ctx.allies}
                 | {ctx.my_champion}
                 | {self.catalog.champion_name(cid) for cid in ctx.bans})
        pool = set(self.store.get_pool().get(ctx.my_role, []))
        counter_threat = self._pool_counter_threat(ctx.my_role, pool)

        scored = []
        for name, info in cand.items():
            if name in taken:
                continue
            row, tier = info["row"], info["tier"]
            plays_my_role = ctx.my_role in info["roles"]
            is_flex = len(info["roles"]) >= 2
            threat = counter_threat.get(name, 0.0)
            total, factors = ban_model.score_ban(
                tier, row.get("pick_rate"), threat, is_flex, plays_my_role)
            category = ban_model.categorize(factors)
            scored.append((total, name, row, tier, threat, factors, category, is_flex))
        # Highest score first; a stronger (lower) tier breaks ties.
        scored.sort(key=lambda x: (-x[0], _tier_num(x[3])))

        out = []
        for total, name, row, tier, threat, factors, category, is_flex in scored[:limit]:
            out.append({
                "name": name,
                "slug": row.get("slug", self.catalog.champion_slug(name)),
                "tier": tier,
                "win_rate": row.get("win_rate"),
                "counters_pool": round(threat, 1) if threat else 0,
                "category": category,
                "factors": {k: round(v, 2) for k, v in factors.items()},
                "reason": ban_model.ban_reason(name, tier, factors, category,
                                               is_flex, name in pool),
            })
        return out

    def _pool_counter_threat(self, role: str, pool: set[str]) -> dict[str, float]:
        """``{enemy_name: total advantage}`` for champions that beat the player's
        pool in ``role`` (advantage_score > 0 against a pool champion)."""
        if not pool:
            return {}
        from sylqon.db.schema import Champion, ChampionCounter
        from sylqon.db.session import get_session
        try:
            session = get_session()
        except Exception:
            return {}
        try:
            pool_ids = [c.id for c in session.query(Champion)
                        .filter(Champion.name.in_(pool)).all()]
            if not pool_ids:
                return {}
            rows = (session.query(ChampionCounter)
                    .filter(ChampionCounter.role == role,
                            ChampionCounter.counter_id.in_(pool_ids),
                            ChampionCounter.advantage_score > 0).all())
            by_id: dict[int, float] = {}
            for r in rows:
                by_id[r.champion_id] = by_id.get(r.champion_id, 0.0) + r.advantage_score
            out: dict[str, float] = {}
            for cid, total in by_id.items():
                champ = session.get(Champion, cid)
                if champ:
                    out[champ.name] = total
            return out
        finally:
            session.close()

    def _role_top(self, ctx: MatchContext, limit: int = 10) -> list[dict]:
        """Best champions for the player's role given the live draft — scored
        across ALL role champions (not just the pool). Each is flagged with
        whether it's in the player's pool so the UI can distinguish them."""
        from sylqon.db import queries
        from sylqon.db.session import get_session
        try:
            session = get_session()
        except Exception:
            return []
        pool = set(self.store.get_pool().get(ctx.my_role, []))
        personal = self.champion_stats_named()
        try:
            ally_names = [a.name for a in ctx.allies] + (
                [ctx.my_champion] if ctx.my_champion else [])
            ally_ids = queries.ids_for_names(session, ally_names)
            enemy_ids = queries.ids_for_names(session, [e.name for e in ctx.enemies])
            # The direct lane opponent (role inferred in F1) carries most of the
            # counter weight — resolve their DB id so the scorer can lane-weight.
            lane_name = next((e.name for e in ctx.enemies
                              if e.role and e.role == ctx.my_role), None)
            lane_enemy_id = (queries.champion_ids_by_name(session, [lane_name]).get(lane_name)
                             if lane_name else None)
            recs = ChampionScorer().get_top_recommendations(
                session, ctx.my_role, ally_ids, enemy_ids,
                pool_names=pool, personal_stats=personal, limit=limit + 5,
                lane_enemy_id=lane_enemy_id)
        except Exception:
            log.debug("role-top scoring failed", exc_info=True)
            return []
        finally:
            session.close()
        taken = ({e.name for e in ctx.enemies} | {a.name for a in ctx.allies}
                 | {self.catalog.champion_name(cid) for cid in ctx.bans})
        patch = self.catalog.patch
        out = []
        for r in recs:
            name = r["champion"]["name"]
            if name in taken:
                continue
            slug = r["champion"].get("slug", "")
            r["champion"]["icon"] = (
                f"https://ddragon.leagueoflegends.com/cdn/{patch}/img/champion/{slug}.png"
                if slug else "")
            r["in_pool"] = name in pool
            out.append(r)
            if len(out) >= limit:
                break
        return out

    # --------------------------------------------------------- recommendation
    @staticmethod
    def _reco_pick_obj(entry: dict, with_ai: bool = False) -> dict:
        """Serialize a scored universe entry into the compact pick object the
        dashboard consumes (name, slug, 0-100 total + component breakdown)."""
        ch = entry["champion"]
        s = entry["score"]
        obj = {
            "name": ch["name"],
            "slug": ch.get("slug", ""),
            "in_pool": entry.get("in_pool", False),
            "total": s["total"],
            "components": {k: s[k] for k in
                           ("counter", "synergy", "meta", "win_rate", "comfort")},
            "reasoning": entry.get("reasoning", ""),
        }
        if with_ai:
            obj["source"] = entry.get("source", "heuristic")
            obj["alternatives"] = entry.get("alternatives", [])
        return obj

    def _compose_universe(self, role_top: list[dict], ranked: list[dict],
                          ai: dict | None, ctx: MatchContext | None = None) -> dict:
        """Build the dual recommendation from the scored universe: an OPTIMAL
        pick (best overall, possibly off-pool — Ollama may refine it) plus the
        player's best in-POOL option, so the UI can show both side by side."""
        optimal_entry = apply_universe_ai_pick(role_top[:8], ai)
        optimal = self._reco_pick_obj(optimal_entry, with_ai=True)
        pool_entry = next((e for e in role_top if e.get("in_pool")), None)
        pool_pick = self._reco_pick_obj(pool_entry) if pool_entry else None
        pool_scored = [{"name": c["name"], "score": c["score"], "notes": c["notes"]}
                       for c in ranked]
        return {
            "pick": optimal["name"],            # back-compat: headline name
            "reasoning": optimal["reasoning"],
            "source": optimal["source"],
            "alternatives": optimal["alternatives"],
            "optimal": optimal,
            "pool_pick": pool_pick,
            "scored": pool_scored,
            "role_top": role_top,
            # Pick-order exposure: how counterable this pick is given the enemy
            # picks still to come (F4). None when ctx isn't available.
            "counter_risk": (self._counter_pick_risk(ctx, optimal["name"])
                             if ctx is not None else None),
        }

    def _counter_pick_risk(self, ctx: MatchContext, pick_name: str) -> dict | None:
        """How exposed the recommended pick is to a still-unrevealed enemy
        counter (F4 pick-order awareness). Zero risk once every enemy is locked —
        they can no longer adapt to you; otherwise counts the strong meta counters
        to this pick in the player's role that the enemy could still pick. Purely
        advisory and best-effort (None when the DB isn't reachable)."""
        remaining = getattr(ctx, "enemy_picks_after_me", 0) or 0
        if not pick_name or remaining <= 0:
            return {"level": "safe", "remaining": 0, "available": 0,
                    "note": "Every enemy is revealed — safe to lock the counter."}
        from sylqon.db.schema import Champion, ChampionCounter
        from sylqon.db.session import get_session
        try:
            session = get_session()
        except Exception:
            return None
        try:
            pick = session.query(Champion).filter_by(name=pick_name).first()
            if pick is None:
                return None
            taken = ({e.name for e in ctx.enemies} | {a.name for a in ctx.allies}
                     | {ctx.my_champion}
                     | {self.catalog.champion_name(cid) for cid in ctx.bans})
            taken_ids = {c.id for c in session.query(Champion)
                         .filter(Champion.name.in_(taken)).all()}
            rows = (session.query(ChampionCounter)
                    .filter(ChampionCounter.role == ctx.my_role,
                            ChampionCounter.counter_id == pick.id,
                            ChampionCounter.advantage_score >= 5.0).all())
            available = sum(1 for r in rows if r.champion_id not in taken_ids)
        except Exception:
            log.debug("counter-pick risk lookup failed", exc_info=True)
            return None
        finally:
            session.close()
        level = "high" if available >= 3 else "moderate" if available >= 1 else "low"
        note = {
            "high": (f"{remaining} enemy pick(s) still to come and {available} strong "
                     "counters open — favour a flexible pick over a greedy one."),
            "moderate": (f"{remaining} enemy pick(s) left; a few counters remain — "
                         "lockable, but not blind-safe."),
            "low": (f"{remaining} enemy pick(s) left but few counters available — "
                    "safe to commit."),
        }[level]
        return {"level": level, "remaining": remaining, "available": available,
                "note": note}

    def _maybe_recommend(self, ctx: MatchContext) -> None:
        """Publish a champion suggestion. Preferred path scores the WHOLE
        available champion universe for the lane (comfort-aware) and surfaces a
        dual optimal + best-in-pool recommendation; if the universe isn't scored
        yet (DB not synced) it falls back to the pool-only heuristic. The
        heuristic result is set immediately and Ollama refines it in the
        background. Deduped on the (role + revealed picks) signature."""
        reco_fp = "|".join(
            [ctx.my_role]
            + sorted(f"E:{e.name}" for e in ctx.enemies)
            + sorted(f"A:{a.name}" for a in ctx.allies)
        )
        if reco_fp == self._last_reco_fp:
            return
        self._last_reco_fp = reco_fp

        # Universal scoring across all pickable champions for the lane.
        self._last_role_top = self._role_top(ctx)

        # Pool heuristic kept for the "YOUR POOL" panel (signed tag-based notes).
        pool = self.store.champions_for_role(ctx.my_role)
        candidates = build_candidates(ctx, pool, self.catalog)
        ranked = heuristic_rank(ctx, candidates) if candidates else []

        if self._last_role_top:
            self.state.set("recommendation",
                           self._compose_universe(self._last_role_top, ranked, None, ctx))
            best = self._last_role_top[0]["champion"]["name"]
            pool_best = next((e["champion"]["name"] for e in self._last_role_top
                              if e.get("in_pool")), "—")
            log.info("Champion suggestion for %s: optimal=%s, best-in-pool=%s",
                     ctx.my_role, best, pool_best)
            if self.engine.available() and (ctx.enemies or ctx.allies):
                threading.Thread(target=self._refine_universe,
                                 args=(ctx, ranked, reco_fp), daemon=True).start()
            return

        # Fallback: no scored universe (DB not synced) — pool-only heuristic.
        if not candidates:
            self.state.set("recommendation", {
                "pick": None, "alternatives": [], "reasoning": "", "source": "none",
                "scored": [], "optimal": None, "pool_pick": None, "role_top": []})
            return
        self.state.set("recommendation",
                       {**apply_ai_pick(ranked, None),
                        "optimal": None, "pool_pick": None, "role_top": []})
        log.info("Champion suggestion for %s: %s (pool-only, %d candidates)",
                 ctx.my_role, ranked[0]["name"], len(candidates))
        if self.engine.available() and (ctx.enemies or ctx.allies):
            threading.Thread(target=self._refine_recommendation,
                             args=(ctx, ranked, reco_fp), daemon=True).start()

    def _refine_universe(self, ctx: MatchContext, ranked: list[dict],
                         reco_fp: str) -> None:
        """Ollama refines the OPTIMAL pick over the scored universe top-N."""
        role_top = self._last_role_top
        scout_players = (self.state.snapshot().get("scout") or {}).get("players")
        try:
            ai = self.engine.evaluate(
                compile_universe_pick_prompt(ctx, role_top[:8], scout_players))
        except Exception:
            log.exception("Universe recommendation AI call failed")
            return
        if reco_fp != self._last_reco_fp:
            return  # draft moved on while we were thinking; drop the stale result
        result = self._compose_universe(self._last_role_top, ranked, ai, ctx)
        self.state.set("recommendation", result)
        log.info("AI optimal pick: %s (%s)", result["pick"], result["source"])

    def _refine_recommendation(self, ctx: MatchContext, ranked: list[dict],
                               reco_fp: str) -> None:
        """Pool-only fallback refine (used when the universe isn't scored)."""
        try:
            ai = self.engine.evaluate(compile_pick_prompt(ctx, ranked))
        except Exception:
            log.exception("Recommendation AI call failed")
            return
        if reco_fp != self._last_reco_fp:
            return  # draft moved on while we were thinking; drop the stale result
        result = {**apply_ai_pick(ranked, ai),
                  "optimal": None, "pool_pick": None, "role_top": self._last_role_top}
        self.state.set("recommendation", result)
        log.info("AI champion suggestion: %s (%s)", result["pick"], result["source"])

    # ------------------------------------------------- champion performance
    def _refresh_champion_stats(self) -> None:
        """Pull recent SR games from the local match history and aggregate a
        per-champion win-rate. Best-effort; failures leave the map empty."""
        if self.client is None:
            return
        try:
            by_id = champion_stats(self.client)
        except Exception:
            log.exception("Champion stats refresh failed")
            return
        named: dict[str, dict] = {}
        for cid, rec in by_id.items():
            info = self.catalog.champion_by_key(cid)
            if not info:
                continue
            games = rec["games"]
            named[info["name"]] = {
                "games": games,
                "wins": rec["wins"],
                "win_rate": rec["wins"] / games if games else 0.0,
            }
        self._merge_self_mastery(named)
        self._champ_stats = named
        self._scout_cache.clear()  # personal stats feed the scout heuristic
        log.info("Champion stats: %d champions over recent SR games", len(named))

    def _merge_self_mastery(self, named: dict[str, dict]) -> None:
        """Fold the player's own CHAMPION-MASTERY-V4 into the per-champion stat
        map so a *mained* champion reads as a comfort pick even with no recent
        games (F5). Best-effort: needs a Riot API key + resolvable self puuid;
        any failure leaves ``named`` untouched. Adds mastery-only champions with
        a zero-game record so the scorer's mastery floor can still lift them."""
        try:
            from sylqon.riot import api as riot_api
            puuid = self._riot_self_puuid()
            if not puuid:
                return
            top = riot_api.get_top_mastery(puuid, count=20) or []
        except Exception:
            log.debug("self mastery fetch failed", exc_info=True)
            return
        for m in top:
            info = self.catalog.champion_by_key(m.get("championId"))
            if not info:
                continue
            rec = named.setdefault(info["name"],
                                   {"games": 0, "wins": 0, "win_rate": 0.0})
            rec["mastery_points"] = m.get("championPoints")
            rec["mastery_level"] = m.get("championLevel")

    def champion_stats_named(self) -> dict[str, dict]:
        return dict(self._champ_stats)

    # ------------------------------------------------------- meta scout
    def _db_role_rows(self, role: str) -> list[dict]:
        """Role tier rows from the synced SQLite DB (same data the Patch Meta
        panel uses), shaped like ``_meta_positions`` rows. Fallback for ban
        suggestions when ``meta_report.json`` is absent. Best-effort: [] on any
        error."""
        from sylqon.db import queries
        from sylqon.db.session import get_session
        try:
            session = get_session()
        except Exception:
            return []
        try:
            champs = queries.champions_for_role(session, role)
            rows = [{
                "champion": c.name,
                "slug": c.slug,
                "tier": ((c.op_gg_stats or {}).get(role) or {}).get("tier"),
                "win_rate": ((c.op_gg_stats or {}).get(role) or {}).get("win_rate"),
                "pick_rate": ((c.op_gg_stats or {}).get(role) or {}).get("pick_rate"),
            } for c in champs]
        except Exception:
            log.debug("DB role-rows fallback failed for %s", role, exc_info=True)
            return []
        finally:
            session.close()
        rows.sort(key=lambda r: (r["tier"] if r["tier"] is not None else 9,
                                 -(r["win_rate"] or 0)))
        return rows

    def _meta_positions(self) -> dict[str, list[dict]]:
        try:
            raw = json.loads(config.META_REPORT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out = {}
        for role, entries in raw.get("positions", {}).items():
            out[role] = [
                {**e, "slug": self.catalog.champion_slug(e.get("champion", ""))}
                for e in entries
            ]
        return out

    def on_pool_changed(self) -> None:
        """Pool edits change the scout's candidate set — drop its cache."""
        self._scout_cache.clear()

    def on_settings_changed(self) -> None:
        """Settings edited from the dashboard — drop derived caches so the next
        request reflects the new region / feature flags (which config readers
        pick up live via ``config.X``)."""
        self._scout_cache.clear()

    def scout(self, role: str) -> dict:
        """A single 'who should I play' recommendation for a role, drawn from
        the meta tier list crossed with the user's pool and personal win-rate.
        Heuristic result is instant and cached; Ollama refines the wording in
        the background when available."""
        if role in self._scout_cache:
            return self._scout_cache[role]
        result = self._heuristic_scout(role)
        self._scout_cache[role] = result
        if result.get("pick") and self.engine.available():
            threading.Thread(target=self._refine_scout, args=(role,),
                             name="ag-scout", daemon=True).start()
        return result

    def _scout_candidates(self, role: str) -> tuple[list[dict], list[str]]:
        """Returns (meta rows for the role, allowed candidate names). Candidates
        are the user's pool intersected with meta, falling back to the whole
        meta list when the pool doesn't overlap."""
        rows = self._meta_positions().get(role, [])
        pool = set(self.store.get_pool().get(role, []))
        in_pool = [r for r in rows if r["champion"] in pool]
        usable = in_pool or rows
        return rows, [r["champion"] for r in usable]

    def _heuristic_scout(self, role: str) -> dict:
        rows, allowed = self._scout_candidates(role)
        if not allowed:
            return {"role": role, "pick": "", "source": "heuristic",
                    "reason": "No meta data for this role yet — sync from op.gg."}
        by_name = {r["champion"]: r for r in rows}
        stats = self._champ_stats

        def rank_key(name: str) -> tuple:
            r = by_name.get(name, {})
            personal = stats.get(name, {})
            # prefer: lower tier number, then personal win-rate (if enough
            # games), then meta win-rate.
            pers_wr = personal["win_rate"] if personal.get("games", 0) >= 3 else 0.0
            return (r.get("tier", 9), -pers_wr, -r.get("win_rate", 0.0))

        ranked = sorted(allowed, key=rank_key)
        pick = ranked[0]
        row = by_name.get(pick, {})
        personal = stats.get(pick)
        return {
            "role": role,
            "pick": pick,
            "slug": row.get("slug", self.catalog.champion_slug(pick)),
            "tier": row.get("tier"),
            "meta_win_rate": row.get("win_rate"),
            "pick_rate": row.get("pick_rate"),
            "personal": personal,
            "alternatives": ranked[1:3],
            "reason": self._scout_reason(pick, row, personal, in_pool=pick in
                                         set(self.store.get_pool().get(role, []))),
            "source": "heuristic",
        }

    @staticmethod
    def _scout_reason(pick: str, row: dict, personal: dict | None, in_pool: bool) -> str:
        bits = [f"{pick} is the strongest call"]
        tier = row.get("tier")
        tier_label = {0: "S+", 1: "S", 2: "A", 3: "B"}.get(tier)
        if tier_label:
            bits.append(f"sitting at {tier_label} tier")
        if row.get("win_rate"):
            bits.append(f"with a {round(row['win_rate'] * 100)}% meta win rate")
        if personal and personal.get("games", 0) >= 3:
            bits.append(f"— and you run {round(personal['win_rate'] * 100)}% "
                        f"on it over {personal['games']} games")
        elif not in_pool:
            bits.append("(not in your pool yet — consider adding it)")
        return " ".join(bits) + "."

    def _refine_scout(self, role: str) -> None:
        rows, allowed = self._scout_candidates(role)
        if not allowed:
            return
        base = self._scout_cache.get(role, {})
        prompt = self._compile_scout_prompt(role, rows, allowed)
        try:
            ai = self.engine.evaluate(prompt)
        except Exception:
            log.exception("Scout AI call failed")
            return
        if not isinstance(ai, dict):
            return
        pick = ai.get("pick") if ai.get("pick") in allowed else base.get("pick")
        reason = (ai.get("reason") or "").strip() or base.get("reason", "")
        row = next((r for r in rows if r["champion"] == pick), {})
        personal = self._champ_stats.get(pick)
        self._scout_cache[role] = {
            **base,
            "pick": pick,
            "slug": row.get("slug", self.catalog.champion_slug(pick or "")),
            "tier": row.get("tier", base.get("tier")),
            "meta_win_rate": row.get("win_rate", base.get("meta_win_rate")),
            "pick_rate": row.get("pick_rate", base.get("pick_rate")),
            "personal": personal,
            "reason": reason,
            "source": "ollama",
        }
        log.info("Scout (%s) refined by Ollama: %s", role, pick)

    def _compile_scout_prompt(self, role: str, rows: list[dict],
                              allowed: list[str]) -> str:
        lines = [
            "You are a League of Legends draft coach. Pick ONE champion for the "
            f"player to play in the {role} role from the ALLOWED list only.",
            "Favour higher tier (S+ > S > A), higher win rate, and — when shown — "
            "the player's own win rate on the champion.",
            "",
            "META (tier 0=S+,1=S,2=A,3=B):",
        ]
        for r in rows:
            stat = self._champ_stats.get(r["champion"])
            personal = (f", your WR {round(stat['win_rate']*100)}% over "
                        f"{stat['games']} games" if stat and stat.get("games", 0) >= 3
                        else "")
            lines.append(f"- {r['champion']}: tier {r.get('tier')}, "
                         f"meta WR {round(r.get('win_rate',0)*100)}%{personal}")
        lines += [
            "",
            f"ALLOWED: {', '.join(allowed)}",
            "",
            'Reply with JSON only: {"pick": "<name from ALLOWED>", '
            '"reason": "<one punchy sentence, <=160 chars, naming the tier and '
            'win rate>"}',
        ]
        return "\n".join(lines)

    def _fetch_live_build(self, champion: str, champion_id: int,
                          role: str) -> dict | None:
        """On a cache miss, fetch a current build — from the hosted Sylqon
        service's own aggregation when configured (SYLQON_META_URL), falling
        back to op.gg — convert it via the standard opgg_to_build pipeline, and
        cache it (with raw_payload so it survives re-conversion). Returns the
        build dict, or None to fall back to the seed."""
        from sylqon.cache.opgg import opgg_to_build
        from sylqon.cache.opgg_fetch import fetch_opgg_payload
        from sylqon.cache.svc_fetch import fetch_sylqon_payload

        log.info("No cached build for %s %s — fetching live", champion, role)
        payload = fetch_sylqon_payload(champion, role)
        source = "sylqon-svc"
        if not payload:
            payload = fetch_opgg_payload(champion_id, role)
            source = "opgg"
        if not payload:
            return None
        build = opgg_to_build(payload, self.catalog)
        if not build:
            log.warning("%s live build for %s %s failed to convert",
                        source, champion, role)
            return None
        self.store.put_build(champion, role, build, source,
                             self.catalog.patch, raw_payload=payload)
        log.info("Live %s build cached for %s %s", source, champion, role)
        return build

    def _refresh_build_async(self, champion: str, champion_id: int,
                             role: str) -> None:
        """Refresh one stale build off the hot path. Guarded so the same
        champion+role is never refreshed twice concurrently."""
        if not champion_id:
            return
        key = (champion, role)
        with self._refresh_lock:
            if key in self._refreshing:
                return
            self._refreshing.add(key)

        def work() -> None:
            try:
                self._fetch_live_build(champion, champion_id, role)
            except Exception:
                log.exception("Background build refresh failed for %s %s",
                              champion, role)
            finally:
                with self._refresh_lock:
                    self._refreshing.discard(key)

        threading.Thread(target=work, name="ag-build-refresh", daemon=True).start()

    def _maybe_warm_builds(self) -> None:
        """Periodically refresh the user's tracked + seeded builds that are stale
        or from an old patch, so a current build is ready before champ select.
        Throttled by ``BUILD_WARM_INTERVAL`` and guarded so only one warm-up runs
        at a time; the fetches happen on a background thread."""
        if not config.BUILD_WARM_INTERVAL:
            return
        if not self.catalog.patch or self.catalog.patch == "current":
            return
        now = time.time()
        if now - self._last_build_warm < config.BUILD_WARM_INTERVAL:
            return
        if not self._warm_lock.acquire(blocking=False):
            return
        self._last_build_warm = now

        def work() -> None:
            try:
                targets = self.store.refresh_targets(self.catalog.patch)
                if not targets:
                    return
                log.info("Warming %d stale build(s) in the background", len(targets))
                for champ, role in targets:
                    if self._stop.is_set():
                        break
                    info = self.catalog.champion_by_name(champ)
                    if not info:
                        continue
                    try:
                        self._fetch_live_build(champ, int(info["key"]), role)
                    except Exception:
                        log.warning("Warm refresh failed for %s %s", champ, role,
                                    exc_info=True)
                    time.sleep(0.2)
            finally:
                self._warm_lock.release()

        threading.Thread(target=work, name="ag-build-warm", daemon=True).start()

    def _maybe_build_rag_index(self) -> None:
        """Keep the RAG embedding indexes (items and/or runes) current with the
        live patch.

        Only does anything when ``SYLQON_RAG_ITEMS`` / ``SYLQON_RAG_RUNES`` is
        enabled. Each ``ensure_*`` no-ops unless the patch or embed model changed,
        so the heavy embedding pass runs at most once per patch; the per-session
        ``_rag_index_patch`` short-circuit avoids even the cheap load/compare on
        every tick. Needs no League client (catalog + Ollama only), so it can
        build at startup."""
        if not (config.RAG_ITEMS_MODE or config.RAG_RUNES_MODE or config.RAG_KIT_MODE):
            return
        if not self.catalog.patch or self.catalog.patch == "current":
            return
        if self._rag_index_patch == self.catalog.patch:
            return
        if not self._rag_index_lock.acquire(blocking=False):
            return

        def work() -> None:
            try:
                ok = True
                if config.RAG_ITEMS_MODE:
                    from sylqon.rag import item_index
                    idx = item_index.ensure_index(self.catalog)
                    ok = ok and bool(idx and idx.get("patch") == self.catalog.patch)
                if config.RAG_RUNES_MODE:
                    from sylqon.rag import rune_index
                    ridx = rune_index.ensure_rune_index(self.catalog)
                    ok = ok and bool(ridx and ridx.get("patch") == self.catalog.patch)
                if config.RAG_KIT_MODE:
                    from sylqon.rag import kit_index
                    kidx = kit_index.ensure_kit_index(self.catalog)
                    ok = ok and bool(kidx and kidx.get("patch") == self.catalog.patch)
                if ok:
                    # Mark done for this patch only when every enabled index is a
                    # confirmed current build; a stale/None result leaves it unset
                    # so a later tick retries.
                    self._rag_index_patch = self.catalog.patch
            except Exception:
                log.warning("RAG index build failed", exc_info=True)
            finally:
                self._rag_index_lock.release()

        threading.Thread(target=work, name="ag-rag-index", daemon=True).start()

    def _maybe_auto_full_sync(self) -> None:
        """Keep the SQLite scoring universe current automatically — no manual
        trigger anywhere. Whenever the live patch differs from the last synced
        patch (including the very first run, where nothing is synced yet), kick
        off a full op.gg → SQLite sync in the background.

        Throttled by ``AUTO_SYNC_CHECK_INTERVAL`` and lock-guarded via
        :meth:`start_full_sync`; needs no League client, so it can run the moment
        the app starts."""
        if not config.AUTO_FULL_SYNC:
            return
        now = time.time()
        if now - self._last_auto_sync_check < config.AUTO_SYNC_CHECK_INTERVAL:
            return
        self._last_auto_sync_check = now
        if self.state.snapshot().get("sync", {}).get("running"):
            return

        def work() -> None:
            self.catalog.refresh_if_stale()
            patch = self.catalog.short_patch
            if not patch or patch == "current":
                return  # offline at boot — retry on the next throttle window
            synced = self.store.get_synced_patch()
            if synced == patch:
                return
            log.info("Auto full sync: scoring DB stale for patch %s "
                     "(last synced %s) — syncing from op.gg",
                     patch, synced or "never")
            self.start_full_sync()

        threading.Thread(target=work, name="ag-auto-sync", daemon=True).start()

    def compile_loadout(self, ctx: MatchContext) -> loadout_mod.Loadout:
        """Cache read -> Ollama counter-analysis -> validated loadout, with
        every stage published to the dashboard."""
        with self._compile_lock:
            self.last_lane_plan = None  # drop any plan from a previous pick
            candidate, source = self.store.get_build(
                ctx.my_champion, ctx.my_role, self.catalog.patch)
            # No real data for this champion (only a generic seed fell out)?
            # Pull the current build straight from op.gg before the AI sees it.
            if source.startswith("seed"):
                live = self._fetch_live_build(ctx.my_champion, ctx.my_champion_id,
                                              ctx.my_role)
                if live is not None:
                    candidate, source = live, "opgg-live"
            elif source == "cache-stale":
                # We have a usable (if old/off-patch) build — serve it now so the
                # draft isn't delayed, and refresh it in the background so the next
                # compile is current.
                self._refresh_build_async(ctx.my_champion, ctx.my_champion_id,
                                          ctx.my_role)
            log.info("Candidate build for %s %s from %s", ctx.my_champion, ctx.my_role, source)

            # Fold the live champion-specific rune page into the seed-derived rune
            # pool so its meta keystone/runes are always legal for this champion
            # (generic role-default fallbacks aren't champion-specific — skip them).
            if not source.startswith("seed-role") and source != "seed-any":
                rune_pool.register_build(ctx.my_champion, candidate)

            # "Standard" force-inject build: always the untouched meta page.
            self.last_standard = loadout_mod.from_candidate(candidate, ctx, source)
            self.last_meta_candidate = candidate
            # Matchup-aware core: when the enemy comp mandates counter coverage
            # the meta combo misses, swap to the best real op.gg combo before
            # anything downstream (AI, enforcement, variants) sees the build.
            # No-op for balanced comps, hidden enemies, or single-combo builds.
            candidate = core_select.apply_core_selection(candidate, ctx, self.catalog)
            # Matchup-aware rune page: swap to the best real op.gg page when the
            # enemy damage skew mandates a defensive rune the meta page misses.
            # No-op for balanced comps or single-page builds.
            candidate = rune_select.apply_rune_selection(candidate, ctx)
            base = loadout_mod.from_candidate(candidate, ctx, source)
            ai_result = None
            if ctx.enemies and self.engine.available():
                self.state.update("ollama", processing=True)
                log.info("Routing match context to %s for counter-analysis", self.engine.model)
                try:
                    if config.OPEN_BUILD_MODE:
                        ai_result = self.engine.evaluate(
                            open_build_prompt.compile_open_prompt(
                                ctx, candidate, self.catalog),
                            options={"num_predict": 768})
                    else:
                        # The counter-loadout JSON can exceed the default 512-token
                        # budget; give it headroom — generation stops at JSON's end.
                        ai_result = self.engine.evaluate(
                            compile_prompt(ctx, candidate, self.catalog),
                            options={"num_predict": 1024})
                finally:
                    self.state.update("ollama", processing=False)
            elif not ctx.enemies:
                log.info("Enemy team hidden; skipping AI counter-analysis")

            if config.OPEN_BUILD_MODE:
                final = loadout_mod.apply_ai_open_decision(
                    base, ai_result, ctx, self.catalog, candidate)
            else:
                final = loadout_mod.apply_ai_decision(
                    base, ai_result, ctx, self.catalog, candidate)
            final.name = final.name or "Recommended"
            # Coach layer: the structured why-list of every deviation from the
            # untouched meta build (last_standard). Best-effort — never blocks.
            try:
                from sylqon.analysis import decisions as decisions_mod
                final.decisions = decisions_mod.build_decisions(
                    final, self.last_standard, candidate, ctx)
            except Exception:  # pragma: no cover - defensive: coaching is optional
                log.debug("decision layer failed; publishing build without it",
                          exc_info=True)
            self.last_candidate, self.last_loadout = candidate, final
            self.last_variants = [final]  # primary only until alternatives generate
            self._publish_build(candidate, final, ctx)
            self._record_decision_telemetry(ctx, final)
        # Generate alternative variants off-thread (a second Ollama call) so the
        # primary build/injection is never delayed; covers both live and demo.
        threading.Thread(target=self._generate_variants, args=(ctx,),
                         name="ag-variants", daemon=True).start()
        # AI lane game-plan (early/mid/late) — independent Ollama call, merged
        # into the build state when it lands so the scorecard shows instantly.
        threading.Thread(target=self._generate_lane_plan, args=(ctx,),
                         name="ag-lane-plan", daemon=True).start()
        return final

    def _record_decision_telemetry(self, ctx: MatchContext,
                                   final: loadout_mod.Loadout) -> None:
        """Persist the compiled loadout's coach decisions (closed-loop eval
        foundation). Best-effort — a telemetry failure must never touch the
        injection path, so all errors are swallowed."""
        try:
            from sylqon.db import queries
            from sylqon.db.session import get_session
            session = get_session()
            try:
                queries.record_decision(
                    session, champion=ctx.my_champion, role=ctx.my_role, loadout=final)
                session.commit()
            finally:
                session.close()
        except Exception:  # pragma: no cover - telemetry is strictly optional
            log.debug("loadout decision telemetry failed", exc_info=True)

    def _publish_build(self, candidate: dict, final: loadout_mod.Loadout,
                       ctx: MatchContext) -> None:
        # "standard" is the untouched meta page; ``candidate`` may already carry
        # the matchup-selected core, and the diff should make that visible.
        std = self.last_meta_candidate or candidate
        std_names = {i["name"] for i in std.get("items", [])}
        opt_names = {i["name"] for i in final.items}
        from sylqon.lcu.lobby import _damage_type
        my_info = self.catalog.champion_by_key(ctx.my_champion_id) or {}
        dmg = _damage_type(my_info)
        skill = self._skill_order(ctx.my_champion, candidate)

        def archetype_of(items: list[dict]) -> str:
            return build_archetype.classify_archetype(items, self.catalog, dmg)

        self.last_matchup = self._matchup_analytics(ctx)

        self.state.set("build", {
            "standard": {
                "items": std.get("items", []),
                "keystone": std.get("keystone"),
                "primary_runes": std.get("primary_runes", []),
                "secondary_style": std.get("secondary_style"),
                "secondary_runes": std.get("secondary_runes", []),
                "stat_shards": std.get("stat_shards", []),
                "spell1": std.get("spell1", "Heal"),
                "skill_order": skill,
                "archetype": archetype_of(std.get("items", [])),
            },
            # Why the primary build's core deviates from meta (None = it doesn't).
            "core_reason": candidate.get("core_reason"),
            "optimized": {**serialize_loadout(final), "skill_order": skill,
                          "archetype": archetype_of(final.items)},
            "diff": {
                "added": sorted(opt_names - std_names),
                "removed": sorted(std_names - opt_names),
            },
            "variants": [
                {**serialize_loadout(v), "priority": i, "primary": i == 0,
                 "name": v.name or ("Recommended" if i == 0 else f"Variant {i + 1}"),
                 "skill_order": skill, "archetype": archetype_of(v.items)}
                for i, v in enumerate(self.last_variants or [final])
            ],
            # Post-lock matchup scorecard (deterministic) + AI lane plan (filled
            # in off-thread once Ollama answers; None until then / when it's down).
            "matchup": self.last_matchup,
            "lane_plan": self.last_lane_plan,
        })

    def _matchup_analytics(self, ctx: MatchContext) -> dict | None:
        """Final-pick scorecard: the locked champion's 0-100 component scores plus
        per-ally synergy / per-enemy counter values and the direct lane matchup.
        DB-only and best-effort — never raises into the publish path."""
        try:
            from sylqon.analysis.matchup import compute_matchup
            from sylqon.db.session import get_session
        except Exception:
            return None
        try:
            session = get_session()
        except Exception:
            return None
        try:
            return compute_matchup(
                session, ctx, self.catalog,
                pool_names=set(self.store.get_pool().get(ctx.my_role, [])),
                personal_stats=self.champion_stats_named())
        except Exception:
            log.debug("matchup analytics failed", exc_info=True)
            return None
        finally:
            session.close()

    def _generate_lane_plan(self, ctx: MatchContext) -> None:
        """Generate the AI early/mid/late lane plan off-thread and re-publish the
        build with it. Best-effort: a failure or Ollama-down leaves the
        deterministic scorecard in place (lane_plan stays None)."""
        if self.last_candidate is None or self.last_loadout is None:
            return
        try:
            from sylqon.ai.lane_plan import LaneCoach
            intel = self.state.snapshot().get("draft_intel")
            scout_players = (self.state.snapshot().get("scout") or {}).get("players")
            plan = LaneCoach(self.engine).plan(ctx, self.last_matchup, intel, scout_players)
        except Exception:
            log.exception("Lane-plan generation failed")
            return
        if plan is None:
            return
        cur = self.last_ctx
        if cur is not None and cur.my_champion_id != ctx.my_champion_id:
            return  # locked pick changed while we were thinking — drop the plan
        self.last_lane_plan = plan
        self._publish_build(self.last_candidate, self.last_loadout, ctx)

    def _skill_order(self, champion: str, candidate: dict) -> list[str]:
        """Skill max-order for the loadout: op.gg's order when the build carries
        one, else the curated static fallback. Empty when unknown."""
        order = candidate.get("skill_order")
        if order:
            return [s for s in order if s in ("Q", "W", "E")][:3]
        return list(static.SKILL_MAX_ORDER.get(champion, []))

    def _generate_variants(self, ctx: MatchContext) -> None:
        """Generate up to 3 build variants and re-publish the build state with
        them. Best-effort: any failure leaves the primary-only build in place."""
        if self.last_candidate is None or self.last_loadout is None:
            return
        if not self._variants_lock.acquire(blocking=False):
            return  # a generation is already in flight
        try:
            candidate, primary = self.last_candidate, self.last_loadout
            self.last_variants = build_variants.generate_variants(
                ctx, candidate, self.catalog, self.engine, primary, max_variants=3,
            )
            self._publish_build(candidate, primary, ctx)
        except Exception:
            log.exception("Build-variant generation failed")
        finally:
            self._variants_lock.release()

    # ------------------------------------------------------------- actions
    def inject_variant(self, index: int) -> dict:
        """Import a specific build variant by index (0 = primary). Overwrites the
        single 'Antigravity Meta' set, so clicking an alternative replaces the
        previously imported build."""
        if self.client is None or not self.client.is_alive():
            return {"ok": False, "detail": "League client not connected"}
        if self.last_ctx is None or not self.last_variants:
            return {"ok": False, "detail": "No build variants compiled yet"}
        if not 0 <= index < len(self.last_variants):
            return {"ok": False, "detail": f"variant {index} out of range"}
        loadout = self.last_variants[index]
        ok = Injector(self.client).inject(
            loadout, self.last_ctx.summoner_id, self.last_ctx.my_champion_id)
        if ok:
            self.last_loadout = loadout  # keep force-inject consistent with the choice
        label = loadout.name or f"variant {index}"
        detail = (f"{label} build injected" if ok
                  else f"{label} build partially injected (spells need an active champ select)")
        self.state.update("injection",
                          status="ok" if ok else "partial", at=time.time(), detail=detail)
        return {"ok": ok, "detail": detail}

    def force_inject(self, variant: str = "optimized") -> dict:
        if self.client is None or not self.client.is_alive():
            return {"ok": False, "detail": "League client not connected"}
        if self.last_ctx is None:
            return {"ok": False, "detail": "No lobby context compiled yet"}
        loadout = self.last_standard if variant == "standard" else self.last_loadout
        if loadout is None:
            return {"ok": False, "detail": "No loadout compiled yet"}
        log.info("Force inject requested (%s build)", variant)
        ok = Injector(self.client).inject(
            loadout, self.last_ctx.summoner_id, self.last_ctx.my_champion_id)
        detail = (f"{variant} build injected" if ok
                  else f"{variant} build partially injected (spells need an active champ select)")
        self.state.update("injection",
                          status="ok" if ok else "partial", at=time.time(), detail=detail)
        return {"ok": ok, "detail": detail}

    def start_full_sync(self) -> dict:
        """Kick off a full op.gg → SQLite sync (all champions, all roles) off the
        request thread, publishing progress to ``state.sync``. Guarded so only one
        runs at a time. This is what populates the universe the live-draft
        role-top / ban / flex features score against."""
        if not self._sync_lock.acquire(blocking=False):
            return {"ok": False, "detail": "a full sync is already running"}

        def work() -> None:
            from sylqon.mcp.sync import run_full_sync
            self.state.update("sync", running=True, done=0, total=0,
                              detail="contacting op.gg…", at=time.time())

            def progress(done: int, total: int) -> None:
                self.state.update("sync", done=done, total=total,
                                  detail=f"{done}/{total} champion-roles synced")

            try:
                result = run_full_sync(progress=progress, store=self.store,
                                       catalog=self.catalog)
                # Mark the patch we just synced so the auto-sync won't re-run
                # until the next patch lands.
                if not result.get("error"):
                    self.store.set_synced_patch(self.catalog.short_patch)
                # refresh the cache stats the dashboard shows
                self._refresh_system_status()
                self.state.update("sync", running=False, at=time.time(),
                                  detail=("sync complete: "
                                          f"{result.get('builds', 0)} builds "
                                          f"({result.get('cached', 0)} cached), "
                                          f"{result.get('counters', 0)} counters, "
                                          f"{result.get('synergies', 0)} synergies"),
                                  last_result=result)
                log.info("Full op.gg sync finished: %s", result)
            except Exception as exc:
                log.exception("Full op.gg sync failed")
                self.state.update("sync", running=False, at=time.time(),
                                  detail=f"sync failed: {exc}")
            finally:
                self._sync_lock.release()

        threading.Thread(target=work, name="ag-full-sync", daemon=True).start()
        return {"ok": True, "detail": "full op.gg sync started"}

    def start_demo(self) -> dict:
        """Synthetic lobby for exercising the dashboard outside champ select.
        Uses the real cache, prompt compiler and Ollama engine."""
        me = self.catalog.champion_by_name("Jinx")
        if not me:
            return {"ok": False, "detail": "catalog not loaded yet; try again shortly"}
        enemies = []
        for name, role in DEMO_ENEMIES:
            info = self.catalog.champion_by_name(name)
            if info:
                enemies.append(_demo_profile(info, role))
        # One teammate still hovering (not locked) so the Demo control also
        # exercises the live-draft cockpit's hover-vs-locked styling.
        allies = []
        ally_info = self.catalog.champion_by_name("Braum")
        if ally_info:
            allies.append(_demo_ally_hover(ally_info, "utility"))
        # Model an in-progress champ select (enemies locked, your counter-pick
        # turn) so the demo lands on the live-draft cockpit — the headline view —
        # rather than skipping straight to the post-lock build screen. The
        # hovering ally is also flagged as the active turn (index 0 of the
        # allies list) so the "on the clock" pulse has something to demo too.
        ctx = MatchContext(
            summoner_id=(self.client.current_summoner() or {}).get("summonerId", 0)
            if self.client else 0,
            my_champion="Jinx", my_champion_id=int(me["key"]), my_role="bottom",
            locked=False, all_locked=False, my_turn=True, enemies=enemies, allies=allies,
            fingerprint=f"demo-{time.time():.0f}",
            active_pick_side="ally" if allies else None, active_pick_index=0 if allies else None,
        )
        log.info("Demo lobby assembled: Jinx vs %s", ", ".join(e.name for e in enemies))
        # Drop any sticky injection flag from a previous game so deriveMode can't
        # push the demo past champ select.
        self.state.set("injection", {"status": "idle", "at": None, "detail": ""})
        self.state.set("draft_clock", {"phase": "PICK", "remaining_ms": 25000, "total_ms": 30000})
        self._publish_lobby(ctx, demo=True)
        self._last_reco_fp = None
        self._maybe_recommend(ctx)
        threading.Thread(target=self.compile_loadout, args=(ctx,), daemon=True).start()
        return {"ok": True, "detail": "demo lobby started"}

    def stop_demo(self) -> dict:
        self.state.set("demo", False)
        self.state.set("lobby", None)
        self.state.set("draft_intel", None)
        self.state.set("recommendation", None)
        self.state.set("build", None)
        self.state.set("draft_clock", None)
        self.state.set("matchups", None)
        self.state.set("callouts", None)
        self.last_ctx = None
        self._reset_draft_state()
        return {"ok": True, "detail": "demo cleared"}


def _norm_position(raw: str) -> str:
    """LCU position string ('TOP', 'utility', 'FILL', '') → role vocab or ''."""
    val = (raw or "").lower()
    if val in ("fill", "unselected", "none"):
        return ""
    from sylqon.data import static
    return static.ROLE_ALIASES.get(val, "")


def _scout_players_from_lobby(data: dict) -> list[dict]:
    """Normalize a ``/lol-lobby/v1/lobby`` resource into scout player dicts. The
    premade lobby always carries puuids, so every member is resolvable."""
    out: list[dict] = []
    for m in data.get("members", []) or []:
        out.append({
            "puuid": m.get("puuid", "") or "",
            "name": (m.get("gameName") or m.get("summonerName") or "").strip(),
            "position": _norm_position(m.get("firstPositionPreference", "")),
            "side": "ally",
            "is_self": bool(m.get("isLocalMember")),
        })
    return out


def _scout_players_from_session(session: dict) -> list[dict]:
    """Normalize a champ-select session's ``myTeam`` into scout player dicts.
    Entries without a puuid (anonymized) are kept so the UI can show a hidden
    card; ``_maybe_scout`` simply won't fetch history for them."""
    cell_id = session.get("localPlayerCellId", -1)
    out: list[dict] = []
    for p in session.get("myTeam", []) or []:
        out.append({
            "puuid": p.get("puuid", "") or "",
            "name": (p.get("gameName") or p.get("summonerName") or "").strip(),
            "position": _norm_position(p.get("assignedPosition", "")),
            "side": "ally",
            "is_self": p.get("cellId") == cell_id,
        })
    return out


def _demo_profile(info: dict, role: str) -> EnemyProfile:
    from sylqon.lcu.lobby import _damage_type, _threats
    return EnemyProfile(
        name=info["name"], champion_id=int(info["key"]), role=role, side="enemy",
        damage_type=_damage_type(info), tags=info.get("tags", []),
        threats=_threats(info["name"]),
        spell1="Ignite", spell2="Flash", locked=True,
    )


def _demo_ally_hover(info: dict, role: str) -> EnemyProfile:
    """A teammate still hovering (not locked) — exercises the live-draft
    cockpit's hover-vs-locked styling from the Demo control."""
    from sylqon.lcu.lobby import _damage_type, _threats
    return EnemyProfile(
        name=info["name"], champion_id=int(info["key"]), role=role, side="ally",
        damage_type=_damage_type(info), tags=info.get("tags", []),
        threats=_threats(info["name"]),
        spell1="Exhaust", spell2="Flash", locked=False,
    )

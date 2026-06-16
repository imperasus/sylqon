"""Observable pipeline runtime.

Wraps the detection -> cache -> Ollama -> injection loop from the original
CLI entrypoint in a runner that publishes every state transition into a
thread-safe AppState snapshot, which the FastAPI bridge serves to the
dashboard. main.py (headless CLI) and server.py (dashboard) both run this.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque

from sylqon import config, loadout as loadout_mod
from sylqon.ai import build_variants
from sylqon.ai.engine import OllamaEngine
from sylqon.ai.prompts import compile_prompt
from sylqon.ai.pick_prompt import (
    apply_ai_pick, apply_universe_ai_pick, build_candidates, compile_pick_prompt,
    compile_universe_pick_prompt, heuristic_rank,
)
from sylqon.analysis import build_archetype, draft_intel
from sylqon.analysis.scoring import ChampionScorer
from sylqon.cache.store import MetaCache
from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.client import LCUClient
from sylqon.lcu.events import ChampSelectListener
from sylqon.lcu.history import champion_stats
from sylqon.lcu.injector import Injector, merge_stat_shards
from sylqon.lcu.lobby import (
    EnemyProfile, MatchContext, display_signature, read_match_context,
)
from sylqon.livegame.client import LiveClient
from sylqon.livegame.engine import MissionEngine
from sylqon.livegame.state import LiveGameState, parse_live_state

log = logging.getLogger(__name__)

DEMO_ENEMIES = [
    ("Malzahar", "middle"), ("Leona", "utility"), ("Zed", "jungle"),
    ("Soraka", "bottom"), ("Malphite", "top"),
]


class AppState:
    """Thread-safe snapshot store + bounded event log for the dashboard."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=80)
        self._state: dict = {
            "lcu": {"connected": False, "phase": "None", "summoner": ""},
            "ollama": {"available": False, "model": config.OLLAMA_MODEL, "processing": False},
            "cache": {"patch": "", "short_patch": "", "builds": 0, "last_sync": None},
            "lobby": None,
            "draft_intel": None,
            "recommendation": None,
            "build": None,
            "injection": {"status": "idle", "at": None, "detail": ""},
            "sync": {"running": False, "done": 0, "total": 0, "detail": "", "at": None},
            "demo": False,
            "live": {"active": False},
            "overlay": {"active": False, "role": "", "missions": [], "game": {}},
        }

    def update(self, section: str, **fields) -> None:
        with self._lock:
            if isinstance(self._state.get(section), dict):
                self._state[section] = {**self._state[section], **fields}
            else:
                self._state[section] = fields

    def set(self, section: str, value) -> None:
        with self._lock:
            self._state[section] = value

    def event(self, level: str, message: str) -> None:
        self._events.append({"ts": time.time(), "level": level, "msg": message})

    def snapshot(self) -> dict:
        with self._lock:
            snap = {k: (dict(v) if isinstance(v, dict) else v) for k, v in self._state.items()}
        snap["events"] = list(self._events)
        snap["ts"] = time.time()
        return snap


class StateLogHandler(logging.Handler):
    """Mirrors pipeline log records into the dashboard event feed."""

    def __init__(self, state: AppState) -> None:
        super().__init__(level=logging.INFO)
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        self.state.event(record.levelname.lower(), record.getMessage())


def _spell_brief(name: str) -> dict | None:
    info = static.SPELL_INFO.get(name)
    if not info:
        return None
    return {"name": name, "category": info[0], "description": info[1]}


def serialize_enemy(e: EnemyProfile, catalog: Catalog) -> dict:
    info = catalog.champion_by_key(e.champion_id) or {}
    return {
        "name": e.name,
        "slug": info.get("id", ""),
        "champion_id": e.champion_id,
        "role": e.role,
        "side": e.side,
        "locked": e.locked,
        "damage_type": e.damage_type,
        "tags": e.tags,
        "threats": e.threats,
        "spells": [s for s in (_spell_brief(e.spell1), _spell_brief(e.spell2)) if s],
    }


def serialize_loadout(l: loadout_mod.Loadout) -> dict:
    return {
        "items": l.items,
        "starting_items": l.starting_items,
        "primary_style_id": l.primary_style_id,
        "secondary_style_id": l.secondary_style_id,
        "rune_perk_ids": l.rune_perk_ids,
        "shard_ids": l.shard_ids,
        "selected_perk_ids": merge_stat_shards(l.rune_perk_ids, l.shard_ids),
        "spell1": l.spell1,
        "spell2": l.spell2,
        "source": l.source,
        "reasoning": l.reasoning,
        "name": l.name,
        # situational alternatives not chosen for the default order — shown as
        # "other options" in the item panel.
        "situational_pool": l.situational_pool,
    }


class PipelineRunner:
    def __init__(self, state: AppState | None = None) -> None:
        self.state = state or AppState()
        self.catalog = Catalog()
        self.store = MetaCache()
        self.engine = OllamaEngine()
        self.client: LCUClient | None = None
        self._listener: ChampSelectListener | None = None
        self._summoner_id: int = 0
        self._compile_lock = threading.Lock()
        self._inject_lock = threading.Lock()
        self._variants_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._stop = threading.Event()
        self._catalog_lcu_supplemented = False
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
        self.last_loadout: loadout_mod.Loadout | None = None
        self.last_standard: loadout_mod.Loadout | None = None
        self.last_variants: list[loadout_mod.Loadout] = []  # [0] = primary (auto-injected)
        self._last_injected_fp: str | None = None
        self._last_reco_fp: str | None = None
        self._last_display_sig: str | None = None
        self._last_trigger_sig: str | None = None
        self._champ_stats: dict[str, dict] = {}     # champion name -> {games, wins, win_rate}
        self._scout_cache: dict[str, dict] = {}     # role -> scout result
        self._last_role_top: list[dict] = []        # universal role top-N for live draft
        logging.getLogger("sylqon").addHandler(StateLogHandler(self.state))
        self._bootstrap_if_empty()

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
        self._stop_listener()
        self._stop_live_poller()
        self.stop_live_demo()

    def _tick(self) -> None:
        """The poll loop now only manages the LCU connection and phase, and
        owns the champ-select WebSocket listener's lifecycle. The heavy draft
        processing is event-driven (see ``_on_session``); polling here is just
        the connection watchdog plus an injection-retry safety net."""
        self._refresh_system_status()

        if self.client is None or not self.client.is_alive():
            was_connected = self.client is not None
            self._stop_listener()
            self.client = LCUClient.connect()
            if self.client is None:
                if was_connected:
                    log.warning("Lost connection to the League client")
                self.state.update("lcu", connected=False, phase="None", summoner="")
                return
            summoner = self.client.current_summoner() or {}
            self._summoner_id = summoner.get("summonerId", 0)
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

        phase = self.client.gameflow_phase()
        self.state.update("lcu", connected=True, phase=phase)

        # The live-game overlay poller only runs during the actual game.
        if phase != "InProgress":
            self._stop_live_poller()

        if phase == "InProgress":
            self._ensure_live_poller()
        elif phase == "ChampSelect":
            self._ensure_listener()
            # Resilience: the WebSocket only pushes *deltas*, so when it isn't
            # running (older client / blocked port) OR nothing has been published
            # yet this champ select, poll the current state so the dashboard
            # switches to Live Draft immediately — without waiting for a hover.
            listener_ok = self._listener and self._listener.is_running()
            if not listener_ok or self.state.snapshot().get("lobby") is None:
                ctx = read_match_context(self.client, self.catalog,
                                         summoner_id=self._summoner_id)
                if ctx:
                    self._publish_lobby(ctx, demo=False)
                    self._maybe_recommend(ctx)
            self._retry_injection_if_pending()
        elif phase in ("Lobby", "Matchmaking", "None", "EndOfGame", "PreEndOfGame"):
            self._stop_listener()
            self._reset_draft_state()
            if not self.state.snapshot().get("demo"):
                self.state.set("lobby", None)
                self.state.set("draft_intel", None)
                self.state.set("recommendation", None)

    # ------------------------------------------------- champ-select listener
    def _ensure_listener(self) -> None:
        """Start the champ-select WebSocket listener if it isn't already up."""
        if self._listener and self._listener.is_running():
            return
        if self.client is None:
            return
        self._listener = ChampSelectListener(self.client.creds, self._on_session)
        self._listener.start()
        # The WS only delivers changes from here on, so seed the CURRENT champ
        # select state right now — otherwise the dashboard wouldn't switch to
        # Live Draft until the first hover/ban generated an event.
        try:
            session = self.client.get_json("/lol-champ-select/v1/session")
            if isinstance(session, dict):
                self._on_session(session, "Create")
        except Exception:
            log.debug("Initial champ-select seed failed", exc_info=True)

    def _stop_listener(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

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

    def _stop_live_poller(self) -> None:
        """Tear the poller down on game end and clear the overlay state."""
        if self._live_thread is None:
            return
        self._live_stop.set()
        self._live_thread = None
        self._mission_engine.tick(LiveGameState.none())  # clear active missions
        self.state.set("live", LiveGameState.none().to_dict())
        self.state.set("overlay", {"active": False, "role": "", "missions": [], "game": {}})
        log.info("Live game poller stopped")
        # The game just ended: generate the next batch of champion missions from
        # its post-game stats (off-thread — a slow Ollama call never blocks polls).
        self._was_in_game = False
        self._schedule_mission_generation()

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
            from sylqon.db.session import get_session
            from sylqon.db.matches import sync_recent_matches
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
        sig = display_signature(data)
        if sig == self._last_display_sig:
            return  # timer tick / nothing visible changed — ignore entirely
        self._last_display_sig = sig

        ctx = read_match_context(self.client, self.catalog, session=data,
                                 summoner_id=self._summoner_id)
        if not ctx:
            return
        self._publish_lobby(ctx, demo=False)  # UI follows every visible change

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
        self.state.set("lobby", {
            "my_champion": ctx.my_champion,
            "my_slug": my_info.get("id", ""),
            "my_role": ctx.my_role,
            "locked": ctx.locked,
            "all_locked": ctx.all_locked,
            "my_turn": ctx.my_turn,
            "enemies": [serialize_enemy(e, self.catalog) for e in ctx.enemies],
            "allies": [serialize_enemy(a, self.catalog) for a in ctx.allies],
            "threat_summary": ctx.team_threat_summary(),
        })
        self.state.set("demo", demo)
        self.last_ctx = ctx
        try:
            self.state.set("draft_intel", self._draft_intel(ctx))
        except Exception:
            log.debug("Draft-intel computation failed", exc_info=True)
            self.state.set("draft_intel", None)

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
        return {
            "enemy_comp": draft_intel.classify_comp(ctx.enemies),
            "ally_comp": draft_intel.classify_comp(ally_picks),
            "counter_pick": draft_intel.counter_pick_advice(ctx),
            "flex_warnings": self._flex_warnings(ctx),
            "ban_suggestions": self._ban_suggestions(ctx),
            "bans": [self.catalog.champion_name(cid) for cid in ctx.bans
                     if self.catalog.champion_name(cid)],
        }

    def _flex_warnings(self, ctx: MatchContext) -> list[dict]:
        """Revealed enemies that can play more than one lane — their final role
        (and thus the matchup) is not yet settled. Best-effort against the DB."""
        from sylqon.db.session import get_session
        from sylqon.db.schema import Champion
        out: list[dict] = []
        try:
            session = get_session()
        except Exception:
            return out
        try:
            for e in ctx.enemies:
                champ = session.query(Champion).filter_by(riot_key=e.champion_id).first()
                roles = list(champ.roles) if champ and champ.roles else []
                if len(roles) > 1:
                    out.append({
                        "name": e.name,
                        "slug": (self.catalog.champion_by_key(e.champion_id) or {}).get("id", ""),
                        "roles": roles,
                        "assigned": e.role,
                    })
        finally:
            session.close()
        return out

    def _ban_suggestions(self, ctx: MatchContext, limit: int = 3) -> list[dict]:
        """Who to ban for the player's role: the strongest meta champions in the
        lane, boosted when they hard-counter the player's pool, minus anything
        already picked or banned. Degrades to pure meta when counter data is thin."""
        rows = self._meta_positions().get(ctx.my_role, [])
        if not rows:
            return []
        taken = ({e.name for e in ctx.enemies} | {a.name for a in ctx.allies}
                 | {ctx.my_champion}
                 | {self.catalog.champion_name(cid) for cid in ctx.bans})
        pool = set(self.store.get_pool().get(ctx.my_role, []))
        counter_threat = self._pool_counter_threat(ctx.my_role, pool)

        scored = []
        for r in rows:
            name = r.get("champion", "")
            if not name or name in taken:
                continue
            tier = r.get("tier")
            tier_num = tier if tier is not None else 9
            threat = counter_threat.get(name, 0.0)
            # lower tier number = stronger; counter advantage breaks ties upward.
            rank = (tier_num, -threat, -(r.get("win_rate") or 0.0))
            scored.append((rank, name, r, tier, threat))
        scored.sort(key=lambda x: x[0])

        out = []
        for _, name, r, tier, threat in scored[:limit]:
            out.append({
                "name": name,
                "slug": r.get("slug", self.catalog.champion_slug(name)),
                "tier": tier,
                "win_rate": r.get("win_rate"),
                "counters_pool": round(threat, 1) if threat else 0,
                "reason": self._ban_reason(name, tier, threat, name in pool),
            })
        return out

    def _pool_counter_threat(self, role: str, pool: set[str]) -> dict[str, float]:
        """``{enemy_name: total advantage}`` for champions that beat the player's
        pool in ``role`` (advantage_score > 0 against a pool champion)."""
        if not pool:
            return {}
        from sylqon.db.session import get_session
        from sylqon.db.schema import Champion, ChampionCounter
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

    @staticmethod
    def _ban_reason(name: str, tier, threat: float, in_pool: bool) -> str:
        tier_label = {0: "S+", 1: "S", 2: "A", 3: "B"}.get(tier)
        bits = [name]
        if tier_label:
            bits.append(f"is {tier_label}-tier in this lane")
        else:
            bits.append("is a lane threat")
        if threat:
            bits.append("and beats champions in your pool")
        elif in_pool:
            bits.append("(also one of yours — denies a mirror)")
        return " ".join(bits) + "."

    def _role_top(self, ctx: MatchContext, limit: int = 10) -> list[dict]:
        """Best champions for the player's role given the live draft — scored
        across ALL role champions (not just the pool). Each is flagged with
        whether it's in the player's pool so the UI can distinguish them."""
        from sylqon.db.session import get_session
        from sylqon.db import queries
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
            recs = ChampionScorer().get_top_recommendations(
                session, ctx.my_role, ally_ids, enemy_ids,
                pool_names=pool, personal_stats=personal, limit=limit + 5)
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
                          ai: dict | None) -> dict:
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
        }

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
                           self._compose_universe(self._last_role_top, ranked, None))
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
        try:
            ai = self.engine.evaluate(compile_universe_pick_prompt(ctx, role_top[:8]))
        except Exception:
            log.exception("Universe recommendation AI call failed")
            return
        if reco_fp != self._last_reco_fp:
            return  # draft moved on while we were thinking; drop the stale result
        result = self._compose_universe(self._last_role_top, ranked, ai)
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
        self._champ_stats = named
        self._scout_cache.clear()  # personal stats feed the scout heuristic
        log.info("Champion stats: %d champions over recent SR games", len(named))

    def champion_stats_named(self) -> dict[str, dict]:
        return dict(self._champ_stats)

    # ------------------------------------------------------- meta scout
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
        """On a cache miss, fetch the current op.gg ranked build, convert it via
        the standard opgg_to_build pipeline, and cache it (with raw_payload so it
        survives re-conversion). Returns the build dict, or None to fall back."""
        from sylqon.cache.opgg import opgg_to_build
        from sylqon.cache.opgg_fetch import fetch_opgg_payload

        log.info("No cached build for %s %s — fetching live from op.gg",
                 champion, role)
        payload = fetch_opgg_payload(champion_id, role)
        if not payload:
            return None
        build = opgg_to_build(payload, self.catalog)
        if not build:
            log.warning("op.gg live build for %s %s failed to convert", champion, role)
            return None
        self.store.put_build(champion, role, build, "opgg",
                             self.catalog.patch, raw_payload=payload)
        log.info("Live op.gg build cached for %s %s", champion, role)
        return build

    def compile_loadout(self, ctx: MatchContext) -> loadout_mod.Loadout:
        """Cache read -> Ollama counter-analysis -> validated loadout, with
        every stage published to the dashboard."""
        with self._compile_lock:
            candidate, source = self.store.get_build(ctx.my_champion, ctx.my_role)
            # No real data for this champion (only a generic seed fell out)?
            # Pull the current build straight from op.gg before the AI sees it.
            if source.startswith("seed"):
                live = self._fetch_live_build(ctx.my_champion, ctx.my_champion_id,
                                              ctx.my_role)
                if live is not None:
                    candidate, source = live, "opgg-live"
            log.info("Candidate build for %s %s from %s", ctx.my_champion, ctx.my_role, source)

            base = loadout_mod.from_candidate(candidate, ctx, source)
            self.last_standard = loadout_mod.from_candidate(candidate, ctx, source)
            ai_result = None
            if ctx.enemies and self.engine.available():
                self.state.update("ollama", processing=True)
                log.info("Routing match context to %s for counter-analysis", self.engine.model)
                try:
                    ai_result = self.engine.evaluate(compile_prompt(ctx, candidate, self.catalog))
                finally:
                    self.state.update("ollama", processing=False)
            elif not ctx.enemies:
                log.info("Enemy team hidden; skipping AI counter-analysis")

            final = loadout_mod.apply_ai_decision(base, ai_result, ctx, self.catalog)
            final.name = final.name or "Recommended"
            self.last_candidate, self.last_loadout = candidate, final
            self.last_variants = [final]  # primary only until alternatives generate
            self._publish_build(candidate, final, ctx)
        # Generate alternative variants off-thread (a second Ollama call) so the
        # primary build/injection is never delayed; covers both live and demo.
        threading.Thread(target=self._generate_variants, args=(ctx,),
                         name="ag-variants", daemon=True).start()
        return final

    def _publish_build(self, candidate: dict, final: loadout_mod.Loadout,
                       ctx: MatchContext) -> None:
        std_names = {i["name"] for i in candidate.get("items", [])}
        opt_names = {i["name"] for i in final.items}
        from sylqon.lcu.lobby import _damage_type
        my_info = self.catalog.champion_by_key(ctx.my_champion_id) or {}
        dmg = _damage_type(my_info)
        skill = self._skill_order(ctx.my_champion, candidate)

        def archetype_of(items: list[dict]) -> str:
            return build_archetype.classify_archetype(items, self.catalog, dmg)

        self.state.set("build", {
            "standard": {
                "items": candidate.get("items", []),
                "keystone": candidate.get("keystone"),
                "primary_runes": candidate.get("primary_runes", []),
                "secondary_style": candidate.get("secondary_style"),
                "secondary_runes": candidate.get("secondary_runes", []),
                "stat_shards": candidate.get("stat_shards", []),
                "spell1": candidate.get("spell1", "Heal"),
                "skill_order": skill,
                "archetype": archetype_of(candidate.get("items", [])),
            },
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
        })

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

    def manual_sync(self) -> dict:
        stats = self.store.stats()
        return {"ok": True, "detail": f"{stats['builds']} builds in cache (OP.GG source)"}

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
                result = run_full_sync(progress=progress)
                # refresh the cache stats the dashboard shows
                self._refresh_system_status()
                self.state.update("sync", running=False, at=time.time(),
                                  detail=("sync complete: "
                                          f"{result.get('builds', 0)} builds, "
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
        # Model an in-progress champ select (enemies locked, your counter-pick
        # turn) so the demo lands on the live-draft cockpit — the headline view —
        # rather than skipping straight to the post-lock build screen.
        ctx = MatchContext(
            summoner_id=(self.client.current_summoner() or {}).get("summonerId", 0)
            if self.client else 0,
            my_champion="Jinx", my_champion_id=int(me["key"]), my_role="bottom",
            locked=False, all_locked=False, my_turn=True, enemies=enemies, allies=[],
            fingerprint=f"demo-{time.time():.0f}",
        )
        log.info("Demo lobby assembled: Jinx vs %s", ", ".join(e.name for e in enemies))
        # Drop any sticky injection flag from a previous game so deriveMode can't
        # push the demo past champ select.
        self.state.set("injection", {"status": "idle", "at": None, "detail": ""})
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
        self.last_ctx = None
        self._reset_draft_state()
        return {"ok": True, "detail": "demo cleared"}


def _demo_profile(info: dict, role: str) -> EnemyProfile:
    from sylqon.lcu.lobby import _damage_type, _threats
    return EnemyProfile(
        name=info["name"], champion_id=int(info["key"]), role=role, side="enemy",
        damage_type=_damage_type(info), tags=info.get("tags", []),
        threats=_threats(info["name"]),
        spell1="Ignite", spell2="Flash", locked=True,
    )

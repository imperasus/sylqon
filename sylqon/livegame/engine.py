"""MissionEngine: keeps at most 1–2 active missions for the player's role,
evaluates them against the live snapshot each tick, and refills empty slots from
the role catalog.

Stateful but side-effect-light: when a mission resolves it calls the optional
``on_resolve(mission, result)`` callback (Phase 3 wires this to the progression
service). The engine itself never touches the DB or the game client.
"""
from __future__ import annotations

import logging
import random
import time
from collections import deque
from typing import Callable

from sylqon import config
from sylqon.livegame.missions import (
    ROLE_CATALOG, MissionRuntime, evaluate, make_runtime,
)
from sylqon.livegame.state import LiveGameState

log = logging.getLogger(__name__)


def _role_catalog(role: str) -> list:
    """Missions for a role, filtered by the optional enabled-types allow-list."""
    enabled = getattr(config, "MISSION_TYPES_ENABLED", None)
    cat = ROLE_CATALOG.get(role, [])
    return [m for m in cat if enabled is None or m.type in enabled]


class MissionEngine:
    def __init__(self, role: str = "", *, max_active: int | None = None,
                 on_resolve: Callable[[object, str], None] | None = None,
                 mission_source: Callable[[str, str], list] | None = None,
                 rng: random.Random | None = None) -> None:
        self.role = role
        self.champion = ""
        self.max_active = max_active or config.OVERLAY_MAX_MISSIONS
        self.on_resolve = on_resolve
        # Supplies the champion's AI-generated mission queue (DB-backed in the
        # runtime). The engine itself stays DB-free: when this is None or returns
        # nothing, it falls back to the static role catalog.
        self.mission_source = mission_source
        self._rng = rng or random.Random()
        self.active: list[MissionRuntime] = []
        self.session_id: str | None = None
        self._session_counter: int = 0
        self._last_time: float = 0.0
        self._recent_ids: deque[str] = deque(maxlen=4)  # avoid immediate repeats
        self._resolved_ids: set[str] = set()            # one-shot queue missions
        self._primary: list = []                         # champion AI queue
        self._fallback: list = _role_catalog(role)       # general role catalog
        self._load_sources()

    def _load_sources(self) -> None:
        """Refresh the champion AI queue (primary) and the role catalog (fallback)
        for the current role/champion."""
        self._fallback = _role_catalog(self.role)
        if self.mission_source is not None and self.champion:
            try:
                self._primary = list(self.mission_source(self.role, self.champion))
            except Exception:
                log.exception("mission_source failed")
                self._primary = []
        else:
            self._primary = []

    def set_role(self, role: str) -> None:
        """Back-compat shim: set role without changing the champion."""
        self.set_context(role, self.champion)

    def set_context(self, role: str, champion: str = "") -> None:
        """Update role and/or champion (from champ-select ctx + live state). Any
        change clears in-flight missions (so we never show a role-incompatible or
        wrong-champion one) and reloads the per-champion queue."""
        role = role or self.role
        champion = champion or self.champion
        if role == self.role and champion == self.champion:
            return
        self.role = role
        self.champion = champion
        self._load_sources()
        self.active = []
        self._recent_ids.clear()
        self._resolved_ids.clear()

    # -- main entry ----------------------------------------------------------
    def tick(self, live: LiveGameState) -> dict:
        if not live.active:
            self.active = []
            self.session_id = None
            return self._payload(live)

        self._maybe_new_session(live)

        survivors: list[MissionRuntime] = []
        for rt in self.active:
            status, progress, detail = evaluate(rt, live)
            rt.status, rt.progress, rt.detail = status, progress, detail
            if status in ("completed", "failed"):
                self._resolved_ids.add(rt.mission.id)  # don't re-serve this game
                if self.on_resolve is not None:
                    try:
                        self.on_resolve(rt.mission, status)
                    except Exception:
                        log.exception("mission on_resolve callback failed")
                log.info("Mission %s -> %s (%s)", rt.mission.id, status, detail)
            else:
                survivors.append(rt)
        self.active = survivors

        self._refill(live)
        return self._payload(live)

    # -- internals -----------------------------------------------------------
    def _maybe_new_session(self, live: LiveGameState) -> None:
        # A fresh game's clock restarts near 0; a drop in game_time => new game.
        new_game = self.session_id is None or (live.game_time + 2.0 < self._last_time)
        self._last_time = live.game_time
        if new_game:
            self._session_counter += 1
            self.session_id = f"s{self._session_counter}-{int(time.time())}"
            self.active = []
            self._recent_ids.clear()
            self._resolved_ids.clear()
            self._load_sources()  # pick up any queue topped-up since the last game
            log.info("Mission session started (role=%s, champion=%s)",
                     self.role or "?", self.champion or "?")

    def _pick(self) -> object | None:
        taken = {rt.mission.id for rt in self.active}

        def usable(m, block_recent: bool = True) -> bool:
            if m.id in taken:
                return False
            # AI queue missions are one-shot per game; general ones may recur.
            if m.id.startswith("cm:") and m.id in self._resolved_ids:
                return False
            if block_recent and m.id in self._recent_ids:
                return False
            return True

        # Queue-first: serve the champion's AI missions before the general pool.
        pool = ([m for m in self._primary if usable(m)]
                or [m for m in self._fallback if usable(m)])
        if not pool:  # everything recently used — relax the no-repeat rule
            pool = ([m for m in self._primary if usable(m, block_recent=False)]
                    or [m for m in self._fallback if usable(m, block_recent=False)])
        return self._rng.choice(pool) if pool else None

    def _refill(self, live: LiveGameState) -> None:
        while len(self.active) < self.max_active:
            m = self._pick()
            if m is None:
                break
            self.active.append(make_runtime(m, live))
            self._recent_ids.append(m.id)

    def _payload(self, live: LiveGameState) -> dict:
        return {
            "active": live.active,
            "role": self.role,
            "missions": [self._mission_dict(rt) for rt in self.active],
            "game": {
                "game_time": live.game_time, "cs": live.cs, "cs_per_min": live.cs_per_min,
                "deaths": live.deaths, "kills": live.kills, "assists": live.assists,
                "ward_score": live.ward_score, "champion": live.champion,
                "level": live.level, "cs_benchmark": live.cs_benchmark,
                "level_diff": live.level_diff, "objective_timers": live.objective_timers,
                "soul": live.soul, "item_spike": live.item_spike,
            },
        }

    @staticmethod
    def _mission_dict(rt: MissionRuntime) -> dict:
        return {
            "id": rt.mission.id, "type": rt.mission.type, "text": rt.mission.text,
            "reward_points": rt.mission.reward_points, "status": rt.status,
            "progress": round(rt.progress, 3), "detail": rt.detail,
        }

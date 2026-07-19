"""Dashboard state container + snapshot serializers.

Extracted from ``runtime.py`` as the first step of decomposing the
``PipelineRunner`` god-object: the thread-safe ``AppState`` snapshot store, the
logging handler that mirrors records into the dashboard event feed, and the
pure serialization helpers that shape internal dataclasses into the JSON the
FastAPI bridge serves. ``runtime.py`` re-exports these names, so existing
imports (``from sylqon.runtime import AppState``) keep working.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from sylqon import config
from sylqon import loadout as loadout_mod
from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.injector import merge_stat_shards
from sylqon.lcu.lobby import EnemyProfile


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
            "draft_clock": None,
            "draft_intel": None,
            "recommendation": None,
            "build": None,
            "injection": {"status": "idle", "at": None, "detail": ""},
            "sync": {"running": False, "done": 0, "total": 0, "detail": "", "at": None},
            "demo": False,
            "live": {"active": False},
            "overlay": {"active": False, "role": "", "missions": [], "game": {}},
            "scout": {"players": [], "ready": False, "at": None},
            "post_game": {"active": False},
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


def _archetypes(pick) -> list[str]:
    """Quick role-archetype tags for a pick (reusing the recommender's
    predicates) — a glanceable read of what the champion brings to the comp."""
    from sylqon.ai.pick_prompt import _is_enchanter, _is_engage, _is_frontline
    threats = set(pick.threats)
    out: list[str] = []
    if _is_engage(pick):
        out.append("Engage")
    elif _is_frontline(pick):
        out.append("Frontline")
    if _is_enchanter(pick):
        out.append("Enchanter")
    if "poke" in threats:
        out.append("Poke")
    if (threats & {"burst_ad", "burst_ap"}) and not _is_frontline(pick):
        out.append("Burst")
    return out[:2]


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
        "archetypes": _archetypes(e),
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
        # Coach layer: structured why-list of every deviation from meta, plus
        # the lane-counter context the post-lock panel and overlay surface.
        "decisions": l.decisions,
        "first_back": l.first_back,
        "lane_opponent_name": l.lane_opponent_name,
    }

"""User-editable runtime settings, persisted to ``cache/user_settings.json``.

These are the values a user changes from the dashboard Settings panel — as
opposed to the env-var defaults in :mod:`sylqon.config`, which are read once at
process start. The store is the runtime source of truth: at import time
``config.py`` overlays any persisted values onto its module constants, and
``PUT /api/settings`` re-applies them live. Almost every config reader uses
``config.X`` attribute access, so reassigning the module constant is picked up
without a restart for the keys marked ``applies="live"``.

This module deliberately imports nothing from :mod:`sylqon.config` to avoid an
import cycle — ``config`` owns the writable path and constructs the store.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# Mission type ids — a mirror of the constants in livegame/missions.py. Hardcoded
# here (rather than imported) to keep this module dependency-free; the offline
# test suite asserts the two stay in sync.
MISSION_TYPE_IDS: frozenset[str] = frozenset({
    "no_death_for_duration", "farm_cs_delta", "cs_per_min_threshold",
    "objective_control", "warding", "roam_assist", "gank_assist",
})

# Declarative description of every user-editable setting. ``attr`` is the
# config.py module attribute the key drives; ``applies`` is "live" when a change
# takes effect without a restart (the reader uses ``config.X`` at call time) or
# "restart" when the value is captured once at startup. ``secret`` masks the
# value in API responses (only set/unset is exposed).
SETTINGS_SPEC: dict[str, dict] = {
    # --- Region & data ---
    "opgg_region":            {"attr": "OPGG_REGION",            "type": "str",    "group": "region",  "applies": "live"},
    "riot_api_region":        {"attr": "RIOT_API_REGION",        "type": "str",    "group": "region",  "applies": "live"},
    "riot_api_mass_region":   {"attr": "RIOT_API_MASS_REGION",   "type": "str",    "group": "region",  "applies": "live"},
    "cache_ttl_seconds":      {"attr": "CACHE_TTL_SECONDS",      "type": "int",    "group": "region",  "applies": "live"},
    "auto_full_sync":         {"attr": "AUTO_FULL_SYNC",         "type": "bool",   "group": "region",  "applies": "live"},
    # --- Riot API ---
    "riot_api_key":           {"attr": "RIOT_API_KEY",           "type": "str",    "group": "riot",    "applies": "live", "secret": True},
    "riot_self_puuid":        {"attr": "RIOT_SELF_PUUID",        "type": "str",    "group": "riot",    "applies": "live"},
    "riot_match_count":       {"attr": "RIOT_MATCH_COUNT",       "type": "int",    "group": "riot",    "applies": "live"},
    # --- AI / Ollama ---
    "ollama_url":             {"attr": "OLLAMA_URL",             "type": "str",    "group": "ai",      "applies": "restart"},
    "ollama_model":           {"attr": "OLLAMA_MODEL",           "type": "str",    "group": "ai",      "applies": "restart"},
    "ollama_timeout_seconds": {"attr": "OLLAMA_TIMEOUT_SECONDS", "type": "int",    "group": "ai",      "applies": "restart"},
    "open_build_mode":        {"attr": "OPEN_BUILD_MODE",        "type": "bool",   "group": "ai",      "applies": "live"},
    "rag_items_mode":         {"attr": "RAG_ITEMS_MODE",         "type": "bool",   "group": "ai",      "applies": "live"},
    "rag_runes_mode":         {"attr": "RAG_RUNES_MODE",         "type": "bool",   "group": "ai",      "applies": "live"},
    "rag_kit_mode":           {"attr": "RAG_KIT_MODE",           "type": "bool",   "group": "ai",      "applies": "live"},
    "rag_fusion_mode":        {"attr": "RAG_FUSION_MODE",        "type": "bool",   "group": "ai",      "applies": "live"},
    # --- Overlay & missions ---
    "overlay_auto":           {"attr": "OVERLAY_AUTO",           "type": "bool",   "group": "overlay", "applies": "live"},
    "overlay_max_missions":   {"attr": "OVERLAY_MAX_MISSIONS",   "type": "int",    "group": "overlay", "applies": "restart"},
    "live_poll_seconds":      {"attr": "LIVE_POLL_SECONDS",      "type": "float",  "group": "overlay", "applies": "restart"},
    "champion_mission_target":{"attr": "CHAMPION_MISSION_TARGET","type": "int",    "group": "overlay", "applies": "restart"},
    "mission_types_enabled":  {"attr": "MISSION_TYPES_ENABLED",  "type": "strset", "group": "overlay", "applies": "restart"},
}


class UserSettings:
    """Thread-safe JSON-backed key/value store for dashboard settings.

    Mirrors the persistence style of :class:`sylqon.cache.store.MetaCache`: a
    single dict written atomically (tmp file + replace) under a lock.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = self._load() or {}

    def _load(self) -> dict | None:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def all(self) -> dict:
        with self._lock:
            return dict(self._data)

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def update(self, patch: dict) -> dict:
        """Merge ``patch`` into the store and persist. Returns a copy of the
        full data after the merge."""
        with self._lock:
            self._data.update(patch)
            self._save()
            return dict(self._data)

"""Central configuration for the Sylqon counter-loadout pipeline."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "sylqon" / "data"
# Writable runtime dir. Overridable via SYLQON_CACHE_DIR so a packaged build
# (where PROJECT_ROOT may be a read-only bundle) can redirect it to a writable
# location such as the desktop app's userData folder.
CACHE_DIR = Path(os.getenv("SYLQON_CACHE_DIR", str(PROJECT_ROOT / "cache")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- Profile mutation guardrail -------------------------------------------
# Every artifact injected into the client carries this exact title. The
# injector overwrites the existing entry with this title (PUT) and never
# accumulates new pages/sets.
PROFILE_TITLE = "Sylqon Meta"

# --- Cache ------------------------------------------------------------------
META_CACHE_PATH = CACHE_DIR / "meta_cache.json"
CATALOG_CACHE_PATH = CACHE_DIR / "ddragon_catalog.json"
META_REPORT_PATH = CACHE_DIR / "meta_report.json"
SEED_BUILDS_PATH = DATA_DIR / "seed_builds.json"

CACHE_TTL_SECONDS = int(os.getenv("AG_CACHE_TTL", 24 * 3600))

# --- Database (v2) ----------------------------------------------------------
# SQLite store for the full champion universe (stats, builds, counters,
# synergies) plus match history and AI analyses. Additive: the live build
# cache above (meta_cache.json) remains the source of truth for injection.
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "sylqon.db"))

# --- Ollama -----------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT", 45))
# Maximum-determinism execution flags + tight token budget + raw JSON output.
OLLAMA_OPTIONS = {
    "temperature": 0.0,
    "top_p": 1.0,
    "top_k": 1,
    "seed": 1337,
    "num_predict": 512,
    "repeat_penalty": 1.0,
}

# --- OP.GG live fetch -------------------------------------------------------
# Region for the undocumented op.gg champion API used when a picked champion has
# no cached build. The meta build is essentially region-agnostic; "na" is fine.
OPGG_REGION = os.getenv("OPGG_REGION", "na")
OPGG_TIMEOUT_SECONDS = int(os.getenv("OPGG_TIMEOUT", 12))

# --- Live Client Data API (in-game overlay coach) ---------------------------
# Riot's local in-game API. READ-ONLY: the overlay only ever GETs this endpoint
# and never writes to / automates the client. Riot ships a self-signed cert for
# 127.0.0.1:2999; pin its CA (riotgames.pem) when available instead of disabling
# TLS verification. Drop the cert at the path below to enable verification.
LIVE_CLIENT_URL = os.getenv("LIVE_CLIENT_URL", "https://127.0.0.1:2999")
LIVE_CLIENT_CERT = DATA_DIR / "riotgames.pem"
LIVE_POLL_SECONDS = float(os.getenv("LIVE_POLL_SECONDS", 1.0))
LIVE_CLIENT_TIMEOUT = float(os.getenv("LIVE_CLIENT_TIMEOUT", 1.5))
OVERLAY_MAX_MISSIONS = int(os.getenv("OVERLAY_MAX_MISSIONS", 2))
# Rolling per-champion mission queue size. After each game on a champion, the AI
# tops the champion's pending queue back up to this many missions (best-effort).
CHAMPION_MISSION_TARGET = int(os.getenv("CHAMPION_MISSION_TARGET", 3))

# Mission difficulty: the "Standard" defaults live in livegame/missions.py; this
# optional JSON map overrides individual tuning keys (durations, cs deltas, ward
# counts). e.g. MISSION_TUNING_JSON='{"no_death_short": 90, "adc_cs_delta": 50}'.
try:
    MISSION_TUNING: dict = json.loads(os.getenv("MISSION_TUNING_JSON", "") or "{}")
except (ValueError, TypeError):
    MISSION_TUNING = {}
# Optional allow-list of enabled mission types (comma-separated). Empty = all on.
_enabled = [t.strip() for t in os.getenv("MISSION_TYPES_ENABLED", "").split(",") if t.strip()]
MISSION_TYPES_ENABLED: set[str] | None = set(_enabled) or None

# --- LCU --------------------------------------------------------------------
LCU_LOCKFILE_OVERRIDE = os.getenv("LOL_LOCKFILE", "")
LCU_LOCKFILE_CANDIDATES = [
    Path(r"C:\Riot Games\League of Legends\lockfile"),
    Path(r"D:\Riot Games\League of Legends\lockfile"),
    Path(os.getenv("LOCALAPPDATA", "")) / "Riot Games" / "League of Legends" / "lockfile",
]
LOBBY_POLL_SECONDS = 2.0

# Writable log location. Overridable via SYLQON_LOG_DIR (see CACHE_DIR note).
LOG_PATH = Path(os.getenv("SYLQON_LOG_DIR", str(PROJECT_ROOT))) / "sylqon.log"

# --- OpenBuild mode ---------------------------------------------------------
# When enabled, the counter-loadout prompt draws from the full Data Dragon
# catalog rather than just the op.gg situational pool.
OPEN_BUILD_MODE: bool = os.getenv("SYLQON_OPEN_BUILD", "0") == "1"
OPEN_BUILD_CATALOG_LIMIT: int = int(os.getenv("SYLQON_OPEN_BUILD_CATALOG_LIMIT", "12"))

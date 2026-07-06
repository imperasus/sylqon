"""Central configuration for the Sylqon counter-loadout pipeline."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root if present (dev convenience; prod uses real env vars).
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass
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

# --- Sylqon hosted meta service (op.gg replacement) --------------------------
# When set (e.g. http://localhost:8090), live-build fetches try the hosted
# Sylqon service's own Match-V5 aggregation FIRST and only fall back to op.gg
# on miss/failure. Empty (the default) keeps the local product's behaviour
# completely unchanged.
SYLQON_META_URL = os.getenv("SYLQON_META_URL", "")
SYLQON_META_TIMEOUT = int(os.getenv("SYLQON_META_TIMEOUT", 6))

# --- OP.GG live fetch -------------------------------------------------------
# Region for the undocumented op.gg champion API used when a picked champion has
# no cached build. The meta build is essentially region-agnostic; "na" is fine.
OPGG_REGION = os.getenv("OPGG_REGION", "na")
OPGG_TIMEOUT_SECONDS = int(os.getenv("OPGG_TIMEOUT", 12))
# Retries for transient op.gg failures (timeout / connection drop / 5xx) before
# falling back to seed/cache. 4xx and malformed JSON are never retried.
OPGG_RETRIES = int(os.getenv("OPGG_RETRIES", 2))
# Parallel network workers for the full op.gg -> SQLite sync. Kept modest so the
# undocumented API isn't hammered; the DB writes stay single-threaded.
OPGG_SYNC_WORKERS = int(os.getenv("OPGG_SYNC_WORKERS", 6))
# Background build warm-up cadence (seconds); 0 disables. Periodically refreshes
# the user's tracked + seeded champions when their build is stale or from an old
# patch, so a current build is ready before champ select.
BUILD_WARM_INTERVAL = int(os.getenv("BUILD_WARM_INTERVAL", 3600))
# Auto-trigger a full sync when the live patch differs from the last synced patch
# (so the scoring universe stays current with no manual trigger at all — including
# the very first run, where nothing is synced yet).
AUTO_FULL_SYNC = os.getenv("SYLQON_AUTO_FULL_SYNC", "1") == "1"
# How often the runtime re-checks whether an auto full sync is due (seconds). The
# check itself is cheap (a cached catalog read + a patch compare); the heavy
# op.gg crawl only runs when the patch actually moved.
AUTO_SYNC_CHECK_INTERVAL = int(os.getenv("SYLQON_AUTO_SYNC_CHECK_INTERVAL", 1800))

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
# Whether the desktop overlay auto-appears when a game starts and hides when it
# ends (the F10 hotkey still toggles it manually). Published in /api/state so the
# Electron shell honors a change made from the dashboard Settings without a
# restart; SYLQON_OVERLAY_AUTO=0 disables it by default.
OVERLAY_AUTO: bool = os.getenv("SYLQON_OVERLAY_AUTO", "1").strip().lower() not in ("0", "false", "no")

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

# --- Riot REST API (live-game scouting via Spectator + LEAGUE + MATCH) -----
RIOT_API_KEY: str = os.getenv("RIOT_API_KEY", "")
# Platform route for SPECTATOR-V5 and LEAGUE-V4 (e.g. euw1 / na1 / kr).
RIOT_API_REGION: str = os.getenv("RIOT_API_REGION", "euw1")
# Mass region for MATCH-V5 (europe / americas / asia).
RIOT_API_MASS_REGION: str = os.getenv("RIOT_API_MASS_REGION", "europe")
# Recent games to pull per player during live-game scouting. Kept modest so the
# 10-player live scout stays well under personal/dev Riot key rate limits (the
# whole scout is fetched before results publish); raise via env with a production
# key for richer fingerprints.
RIOT_MATCH_COUNT: int = int(os.getenv("RIOT_MATCH_COUNT", 20))
# Global cap on concurrent Riot HTTP requests. Match histories are fetched in
# parallel (per player, and across the 10-player roster), so a shared ceiling
# keeps bursts under the key's rate limit no matter how many scout threads run.
# Dev keys are bursty-but-shallow (~20 req/s, 100/2min) — 10 is a safe default;
# raise it with a production key.
RIOT_MAX_CONCURRENCY: int = int(os.getenv("RIOT_MAX_CONCURRENCY", 10))
# Per-player match-fetch fan-out. Bounded again by RIOT_MAX_CONCURRENCY, so this
# is just how wide one player's history fetch may spread.
RIOT_MATCH_FETCH_WORKERS: int = int(os.getenv("RIOT_MATCH_FETCH_WORKERS", 8))
# MATCH-V5 objects are immutable once a game ends, so they're cached in-process
# (bounded LRU) — premades share recent games, and re-scouts hit the same ids, so
# the cache collapses a lot of duplicate fetches. TTL bounds memory on long runs.
RIOT_MATCH_CACHE_SIZE: int = int(os.getenv("RIOT_MATCH_CACHE_SIZE", 2000))
RIOT_MATCH_CACHE_TTL: int = int(os.getenv("RIOT_MATCH_CACHE_TTL", 3600))
# The account owner's PUUID (key-specific — regenerate when the API key changes).
RIOT_SELF_PUUID: str = os.getenv("RIOT_SELF_PUUID", "")

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

# --- Logging / debug --------------------------------------------------------
# Runtime log verbosity. ``SYLQON_DEBUG=1`` is a convenience shortcut that
# forces DEBUG (so the ~23 log.debug() calls scattered across the pipeline
# become visible); otherwise ``SYLQON_LOG_LEVEL`` picks the level by name.
SYLQON_DEBUG: bool = os.getenv("SYLQON_DEBUG", "0") == "1"
LOG_LEVEL: str = "DEBUG" if SYLQON_DEBUG else os.getenv("SYLQON_LOG_LEVEL", "INFO").upper()
# Emit one JSON object per line instead of the human format (off by default).
LOG_JSON: bool = os.getenv("SYLQON_LOG_JSON", "0") == "1"
# Rotating file handler bounds so sylqon.log can't grow without limit.
LOG_MAX_BYTES: int = int(os.getenv("SYLQON_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUP_COUNT: int = int(os.getenv("SYLQON_LOG_BACKUP_COUNT", "3"))

# --- OpenBuild mode ---------------------------------------------------------
# When enabled, the counter-loadout prompt draws from the full Data Dragon
# catalog rather than just the op.gg situational pool.
OPEN_BUILD_MODE: bool = os.getenv("SYLQON_OPEN_BUILD", "0") == "1"
OPEN_BUILD_CATALOG_LIMIT: int = int(os.getenv("SYLQON_OPEN_BUILD_CATALOG_LIMIT", "12"))

# --- RAG item retrieval (experimental) --------------------------------------
# Enhances OpenBuild's catalog suggestions: instead of the hand-maintained
# ITEM_COUNTER_TAGS table (catalog.items_for_threat), the situational catalog
# pool is sourced by semantic similarity between the enemy threat profile and
# each item's real Data Dragon description. Requires SYLQON_OPEN_BUILD=1 (it
# only feeds the open-build path) and a local embedding model in Ollama.
# Fully graceful: if the index is missing or embedding fails, the build path
# falls back to items_for_threat() automatically.
RAG_ITEMS_MODE: bool = os.getenv("SYLQON_RAG_ITEMS", "0") == "1"
# Local Ollama embedding model. nomic-embed-text is small, fast and offline.
RAG_EMBED_MODEL: str = os.getenv("SYLQON_RAG_EMBED_MODEL", "nomic-embed-text")
RAG_EMBED_TIMEOUT_SECONDS: int = int(os.getenv("SYLQON_RAG_EMBED_TIMEOUT", 30))
# Prebuilt item embedding index (a pure derivative of the DDragon catalog, so it
# lives next to ddragon_catalog.json and shares its patch lifecycle).
RAG_ITEM_INDEX_PATH = CACHE_DIR / "item_embeddings.json"
RAG_ITEM_LIMIT: int = int(os.getenv("SYLQON_RAG_ITEM_LIMIT", "12"))

# Same idea for runes: grounds the flexible/secondary rune picks in real DDragon
# rune descriptions instead of the hand-coded rune_directives(). Keystone stays
# champion/meta-anchored — RAG only enriches the flex slots. Requires
# SYLQON_OPEN_BUILD=1; falls back to rune_directives() on any failure.
RAG_RUNES_MODE: bool = os.getenv("SYLQON_RAG_RUNES", "0") == "1"
RAG_RUNE_INDEX_PATH = CACHE_DIR / "rune_embeddings.json"
RAG_RUNE_LIMIT: int = int(os.getenv("SYLQON_RAG_RUNE_LIMIT", "6"))

# Champion-kit grounding (Pattern B — factual, not counter-selection): embeds
# every champion ability (passive + Q/W/E/R) from DDragon championFull.json and
# injects a FACT SHEET of the real, matchup-relevant abilities into the lane-plan
# prompt so the LLM references actual kits instead of hallucinating. Independent
# of OpenBuild; falls back to an ungrounded plan on any failure.
RAG_KIT_MODE: bool = os.getenv("SYLQON_RAG_KIT", "0") == "1"
RAG_KIT_INDEX_PATH = CACHE_DIR / "kit_embeddings.json"
RAG_KIT_LIMIT: int = int(os.getenv("SYLQON_RAG_KIT_LIMIT", "6"))

# Scout + kit fusion: fuses each scouted ENEMY's behavioural fingerprint
# (playstyle, comfort pick, recent form, premade) WITH their champion's key
# ability (from the kit index) into a per-enemy block in the lane plan. Reuses
# the kit index — no new index. Needs enemy scout data (present in-game / normal
# draft; absent in ranked solo where enemies are anonymised → silently skipped).
RAG_FUSION_MODE: bool = os.getenv("SYLQON_RAG_FUSION", "0") == "1"

# --- User settings overlay (dashboard Settings panel) -----------------------
# Persisted user choices live in cache/user_settings.json and take precedence
# over the env/default constants above. Imported last so every constant a key
# may override already exists; see sylqon/settings.py for the schema.
from sylqon.settings import MISSION_TYPE_IDS, SETTINGS_SPEC, UserSettings  # noqa: E402

USER_SETTINGS = UserSettings(CACHE_DIR / "user_settings.json")


def _coerce_setting(spec_type: str, value):
    """Coerce a JSON-stored setting value to the type the config constant uses."""
    if spec_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if spec_type == "int":
        return int(value)
    if spec_type == "float":
        return float(value)
    if spec_type == "strset":
        items = [str(v).strip() for v in (value or []) if str(v).strip()]
        return set(items) or None
    return str(value)


def apply_settings() -> None:
    """Overlay persisted user settings onto the module constants. Runs at import
    (startup) and after every PUT /api/settings, so ``config.X`` readers see
    runtime edits without a restart for keys whose readers re-read ``config.X``."""
    data = USER_SETTINGS.all()
    for key, spec in SETTINGS_SPEC.items():
        if key not in data:
            continue
        try:
            globals()[spec["attr"]] = _coerce_setting(spec["type"], data[key])
        except (ValueError, TypeError):
            log.warning("Ignoring invalid persisted setting %s=%r", key, data[key])


def settings_payload() -> dict:
    """Effective settings (env/default overlaid with user overrides) plus per-key
    metadata for the dashboard. Secret values are masked to a set/unset boolean;
    set-typed values are returned as sorted lists for JSON."""
    out: dict = {}
    for key, spec in SETTINGS_SPEC.items():
        raw = globals().get(spec["attr"])
        if spec["type"] == "strset":
            value = sorted(raw) if raw else []
        elif spec.get("secret"):
            value = bool(raw)
        else:
            value = raw
        out[key] = {
            "value": value,
            "type": spec["type"],
            "group": spec["group"],
            "applies": spec["applies"],
            "secret": spec.get("secret", False),
        }
    return out


def update_settings(patch: dict) -> dict:
    """Validate, persist and live-apply a settings patch from the dashboard.

    Unknown keys and uncoercible values are ignored; an empty secret value means
    'leave unchanged' (so saving the form never wipes a stored credential).
    Returns the fresh :func:`settings_payload`."""
    clean: dict = {}
    for key, value in (patch or {}).items():
        spec = SETTINGS_SPEC.get(key)
        if not spec:
            continue
        if spec.get("secret") and (value is None or value == ""):
            continue
        try:
            coerced = _coerce_setting(spec["type"], value)
        except (ValueError, TypeError):
            continue
        if spec["type"] == "strset":
            # Persist as a JSON-friendly sorted list; drop unknown mission ids so
            # a stale client can never disable the engine with garbage values.
            items = sorted(coerced or [])
            if spec["attr"] == "MISSION_TYPES_ENABLED":
                items = [i for i in items if i in MISSION_TYPE_IDS]
            clean[key] = items
        else:
            clean[key] = coerced
    if clean:
        USER_SETTINGS.update(clean)
        apply_settings()
    return settings_payload()


# Apply persisted overrides now that the helpers and all constants exist.
apply_settings()

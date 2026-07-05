"""Environment-based settings for the ingestion service.

Standalone by design: this service must not import from the local ``sylqon``
package so it stays independently containerizable. It does, however, accept the
same env-var names the local app already uses (``RIOT_API_REGION`` /
``RIOT_API_MASS_REGION``) as fallbacks, so the repo-root ``.env`` works as-is.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

_SERVICE_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SERVICE_ROOT.parent.parent

# Service-local .env wins over the repo-root one; real env vars win over both.
load_dotenv(_SERVICE_ROOT / ".env")
load_dotenv(_REPO_ROOT / ".env")


def _env(name: str, default: str, *fallbacks: str) -> str:
    for key in (name, *fallbacks):
        value = os.getenv(key)
        if value:
            return value
    return default


def _rate(spec: str) -> tuple[int, float]:
    """Parse a '450/10' rate spec into (permits, window_seconds)."""
    permits, _, window = spec.partition("/")
    return int(permits), float(window)


RIOT_API_KEY = _env("RIOT_API_KEY", "")
RIOT_PLATFORM_REGION = _env("RIOT_PLATFORM_REGION", "euw1", "RIOT_API_REGION")
RIOT_MASS_REGION = _env("RIOT_MASS_REGION", "europe", "RIOT_API_MASS_REGION")
RIOT_MATCH_COUNT = int(_env("RIOT_MATCH_COUNT", "20"))
RIOT_REQUEST_TIMEOUT = float(_env("RIOT_REQUEST_TIMEOUT", "10"))
RIOT_MAX_RETRIES = int(_env("RIOT_MAX_RETRIES", "2"))

DATABASE_URL = _env(
    "DATABASE_URL", "postgresql+psycopg://sylqon:sylqon@localhost:5433/sylqon"
)
REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")

# Dual-window budget sized for a production key (500/10s + 30000/10min) with a
# 10% safety margin. Override both for a personal key: "18/1" and "95/120".
RATELIMIT_MODE = _env("RATELIMIT_MODE", "redis")  # "redis" | "memory"
RATE_LIMIT_BURST = _rate(_env("RATE_LIMIT_BURST", "450/10"))
RATE_LIMIT_SUSTAINED = _rate(_env("RATE_LIMIT_SUSTAINED", "27000/600"))
RATE_LIMIT_MAX_WAIT = float(_env("RATE_LIMIT_MAX_WAIT", "300"))

# Heuristic thresholds, overridable as a JSON object (same pattern as the local
# app's MISSION_TUNING_JSON).
ADVICE_TUNING: dict = json.loads(_env("ADVICE_TUNING_JSON", "{}"))

# Own-data benchmarks replace the seed tables per role once this many samples
# have been aggregated for that role (every stored SR match adds 2 per role).
BENCHMARK_MIN_SAMPLES = int(_env("BENCHMARK_MIN_SAMPLES", "40"))

# Discord delivery (webhook MVP — the JDA-style gateway/slash-commands come
# later with account linking). Watcher polls tracked PUUIDs and posts the
# post-game advice to the webhook channel.
DISCORD_WEBHOOK_URL = _env("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN = _env("DISCORD_BOT_TOKEN", "")
WATCH_PUUIDS = [p.strip() for p in _env("WATCH_PUUIDS", "", "RIOT_SELF_PUUID").split(",") if p.strip()]
WATCH_POLL_SECONDS = float(_env("WATCH_POLL_SECONDS", "180"))
WATCH_MATCH_COUNT = int(_env("WATCH_MATCH_COUNT", "5"))
WATCH_LANG = _env("WATCH_LANG", "hu")

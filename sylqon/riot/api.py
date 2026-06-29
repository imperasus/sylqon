"""Thin Riot REST client using the official API key.

Covers the three endpoints needed for live-game scouting:
  - SPECTATOR-V5  → active game (all 10 PUUIDs + team assignments)
  - LEAGUE-V4     → ranked stats per puuid
  - MATCH-V5      → match history per puuid (mass region)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from urllib.parse import quote

import requests

from sylqon import config

log = logging.getLogger(__name__)

_PLATFORM = "https://{region}.api.riotgames.com"
_MASS = "https://{region}.api.riotgames.com"

# Global concurrency budget shared by every Riot call. Match histories fan out
# across many threads (per player × the 10-player roster), so this ceiling — not
# the size of any one thread pool — is what keeps request bursts under the key's
# rate limit. Sized once from config; the 429 handler in `_get` still backs off
# under it if the rate limit is hit anyway.
_SEM = threading.BoundedSemaphore(max(1, config.RIOT_MAX_CONCURRENCY))


def _headers() -> dict:
    return {"X-Riot-Token": config.RIOT_API_KEY}


def _get(url: str, params: dict | None = None, retries: int = 2) -> dict | list | None:
    for attempt in range(retries + 1):
        try:
            with _SEM:
                r = requests.get(url, headers=_headers(), params=params, timeout=10)
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 2))
                log.warning("Riot API rate-limited, waiting %ds", retry_after)
                time.sleep(retry_after)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            log.warning("Riot API request failed (attempt %d): %s", attempt + 1, exc)
    return None


def get_active_game_by_puuid(puuid: str) -> dict | None:
    """SPECTATOR-V5: returns the full active game object or None."""
    base = _PLATFORM.format(region=config.RIOT_API_REGION)
    return _get(f"{base}/lol/spectator/v5/active-games/by-summoner/{puuid}")


def get_ranked_stats(puuid: str) -> list | None:
    """LEAGUE-V4: returns list of ranked entry dicts for the puuid."""
    base = _PLATFORM.format(region=config.RIOT_API_REGION)
    return _get(f"{base}/lol/league/v4/entries/by-puuid/{puuid}")


def get_match_ids(puuid: str, count: int | None = None,
                  queue: int | None = None) -> list[str]:
    """MATCH-V5: newest match IDs for a puuid.

    ``queue`` filters to a single queue id (e.g. 420 ranked solo); when ``None``
    (the default) all queues are returned so Normal Draft games count too — the
    caller filters to Summoner's Rift queues when normalizing. Most players queue
    with their premade in normals, so this also feeds premade detection."""
    base = _MASS.format(region=config.RIOT_API_MASS_REGION)
    count = count or config.RIOT_MATCH_COUNT
    params: dict = {"count": count}
    if queue is not None:
        params["queue"] = queue
    result = _get(
        f"{base}/lol/match/v5/matches/by-puuid/{puuid}/ids",
        params=params,
    )
    return result if isinstance(result, list) else []


def get_account_by_riot_id(game_name: str, tag_line: str) -> dict | None:
    """ACCOUNT-V1: resolve a Riot ID (gameName#tagLine) to {puuid, gameName,
    tagLine}. Used to recover the encrypted PUUID when the LCU only hands back a
    short internal id that SPECTATOR-V5 rejects. Mass-region endpoint."""
    if not game_name or not tag_line:
        return None
    base = _MASS.format(region=config.RIOT_API_MASS_REGION)
    return _get(
        f"{base}/riot/account/v1/accounts/by-riot-id/"
        f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
    )


_MATCH_CACHE: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_MATCH_CACHE_LOCK = threading.Lock()


def _match_cache_get(match_id: str) -> dict | None:
    with _MATCH_CACHE_LOCK:
        hit = _MATCH_CACHE.get(match_id)
        if hit is None:
            return None
        ts, data = hit
        if time.time() - ts > config.RIOT_MATCH_CACHE_TTL:
            _MATCH_CACHE.pop(match_id, None)
            return None
        _MATCH_CACHE.move_to_end(match_id)   # mark most-recently used
        return data


def _match_cache_put(match_id: str, data: dict) -> None:
    with _MATCH_CACHE_LOCK:
        _MATCH_CACHE[match_id] = (time.time(), data)
        _MATCH_CACHE.move_to_end(match_id)
        while len(_MATCH_CACHE) > config.RIOT_MATCH_CACHE_SIZE:
            _MATCH_CACHE.popitem(last=False)   # evict least-recently used


def clear_match_cache() -> None:
    """Drop the in-process MATCH-V5 cache (used by tests)."""
    with _MATCH_CACHE_LOCK:
        _MATCH_CACHE.clear()


def get_match(match_id: str) -> dict | None:
    """MATCH-V5: full match object.

    Cached in-process (bounded LRU + TTL): match data is immutable once the game
    ends, and the same ids recur heavily — premades share recent games, and back-
    to-back scouts re-request the same history — so the cache collapses a large
    share of the fetches that dominate live-scout latency. Only successful
    responses are cached; a None (404 / transient failure) is left re-fetchable."""
    cached = _match_cache_get(match_id)
    if cached is not None:
        return cached
    base = _MASS.format(region=config.RIOT_API_MASS_REGION)
    data = _get(f"{base}/lol/match/v5/matches/{match_id}")
    if isinstance(data, dict):
        _match_cache_put(match_id, data)
    return data


def get_top_mastery(puuid: str, count: int = 5) -> list | None:
    """CHAMPION-MASTERY-V4: top N champions by mastery points for a puuid."""
    base = _PLATFORM.format(region=config.RIOT_API_REGION)
    return _get(
        f"{base}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top",
        params={"count": count},
    )


def get_mastery_by_champion(puuid: str, champion_id: int) -> dict | None:
    """CHAMPION-MASTERY-V4: mastery for one specific champion (used to surface
    mastery on the champ a player is currently on when it's outside their top-N).
    Returns None when the player has no mastery entry for that champion."""
    base = _PLATFORM.format(region=config.RIOT_API_REGION)
    return _get(
        f"{base}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
        f"/by-champion/{champion_id}"
    )

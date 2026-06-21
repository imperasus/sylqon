"""Thin Riot REST client using the official API key.

Covers the three endpoints needed for live-game scouting:
  - SPECTATOR-V5  → active game (all 10 PUUIDs + team assignments)
  - LEAGUE-V4     → ranked stats per puuid
  - MATCH-V5      → match history per puuid (mass region)
"""
from __future__ import annotations

import logging
import time

import requests

from sylqon import config

log = logging.getLogger(__name__)

_PLATFORM = "https://{region}.api.riotgames.com"
_MASS = "https://{region}.api.riotgames.com"


def _headers() -> dict:
    return {"X-Riot-Token": config.RIOT_API_KEY}


def _get(url: str, params: dict | None = None, retries: int = 2) -> dict | list | None:
    for attempt in range(retries + 1):
        try:
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


def get_match_ids(puuid: str, count: int | None = None) -> list[str]:
    """MATCH-V5: newest ranked solo match IDs for a puuid."""
    base = _MASS.format(region=config.RIOT_API_MASS_REGION)
    count = count or config.RIOT_MATCH_COUNT
    result = _get(
        f"{base}/lol/match/v5/matches/by-puuid/{puuid}/ids",
        params={"queue": 420, "count": count},   # 420 = ranked solo/duo
    )
    return result if isinstance(result, list) else []


def get_match(match_id: str) -> dict | None:
    """MATCH-V5: full match object."""
    base = _MASS.format(region=config.RIOT_API_MASS_REGION)
    return _get(f"{base}/lol/match/v5/matches/{match_id}")
